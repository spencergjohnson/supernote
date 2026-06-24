import logging
import time
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.server.db.models.file import RecycleFileDO, UserFileDO
from supernote.server.exceptions import FileAlreadyExists, InvalidPath, QuotaExceeded

logger = logging.getLogger(__name__)


class VirtualFileSystem:
    """Core implementation of the Database-Driven Virtual Filesystem."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create_directory(
        self, user_id: int, parent_id: int, name: str
    ) -> UserFileDO:
        """Create a new directory."""
        # Check if already exists
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.file_name == name,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "Y",
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            # TODO: Determine what the API semantic are and if we should
            # raise an error or not. This requires auditing the client code
            # and callers. (could add exist_ok param etc)
            return existing

        now_ms = int(time.time() * 1000)
        new_dir = UserFileDO(
            user_id=user_id,
            directory_id=parent_id,
            file_name=name,
            is_folder="Y",
            size=0,
            create_time=now_ms,
            update_time=now_ms,
            is_active="Y",
        )
        self.db.add(new_dir)
        await self.db.commit()
        await self.db.refresh(new_dir)
        return new_dir

    async def list_directory(self, user_id: int, parent_id: int) -> list[UserFileDO]:
        """List immediate children of a directory."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.is_active == "Y",
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_recursive(
        self, user_id: int, parent_id: int, base_path: str = ""
    ) -> list[tuple[UserFileDO, str]]:
        """List all descendants of a directory recursively.

        Returns a list of tuples: (node, relative_path_from_parent).
        """
        results: list[tuple[UserFileDO, str]] = []

        children = await self.list_directory(user_id, parent_id)
        for child in children:
            child_rel_path = (
                f"{base_path}/{child.file_name}" if base_path else child.file_name
            )
            results.append((child, child_rel_path))

            if child.is_folder == "Y":
                sub_results = await self.list_recursive(
                    user_id, child.id, child_rel_path
                )
                results.extend(sub_results)

        return results

    async def create_file(
        self,
        user_id: int,
        parent_id: int,
        name: str,
        size: int,
        md5: str,
        storage_key: str,
        quota: int | None = None,
    ) -> UserFileDO:
        """Create or replace a file entry, soft-deleting any prior version to the recycle bin.

        Steps (all in one transaction):
        1. Find all active, non-folder rows with the same (user_id, parent_id, name).
        2. Same-hash short-circuit: if there is exactly one existing active row whose
           md5 matches the incoming md5, return it as-is (no-op re-sync).
        3. Replace-aware quota enforcement (only when ``quota`` is provided): the new
           row adds ``size`` bytes, but the existing same-name rows that step 4 soft-
           deletes free their bytes first, so the *net* change is
           ``size - sum(existing sizes)``. Because the same-hash short-circuit in
           step 2 already returned, an unchanged re-sync is never evaluated here and
           can never be falsely rejected. Performed inside this transaction so the
           usage read and the insert are atomic (no TOCTOU window).
        4. Soft-delete each existing match: set is_active="N" and add a RecycleFileDO entry,
           exactly as delete_node does, so old versions appear in the recycle bin.
        5. Insert the new active row.
        """
        now_ms = int(time.time() * 1000)

        # Step 1: Find existing active files with the same name in this directory.
        existing_stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.file_name == name,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "N",
        )
        existing_result = await self.db.execute(existing_stmt)
        existing_files = list(existing_result.scalars().all())

        # Step 2: Same-hash short-circuit — no-op re-sync.
        if len(existing_files) == 1 and existing_files[0].md5 == md5:
            return existing_files[0]

        # Step 3: Replace-aware quota enforcement.
        if quota is not None:
            used = await self.get_total_usage(user_id)
            replaced = sum(existing.size or 0 for existing in existing_files)
            projected = used - replaced + size
            if projected > quota:
                raise QuotaExceeded(
                    f"Storage quota exceeded: {projected} bytes required, "
                    f"quota is {quota} bytes"
                )

        # Step 4: Soft-delete each existing match to the recycle bin.
        for existing in existing_files:
            existing.is_active = "N"
            existing.deleted_root_id = existing.id  # single-file overwrite grouping
            recycle = RecycleFileDO(
                user_id=user_id,
                file_id=existing.id,
                file_name=existing.file_name,
                size=existing.size,
                is_folder=existing.is_folder,
                delete_time=now_ms,
            )
            self.db.add(recycle)

        # Step 5: Insert the new active row.
        new_file = UserFileDO(
            user_id=user_id,
            directory_id=parent_id,
            file_name=name,
            is_folder="N",
            size=size,
            md5=md5,
            storage_key=storage_key,
            create_time=now_ms,
            update_time=now_ms,
            is_active="Y",
        )
        self.db.add(new_file)
        await self.db.commit()
        await self.db.refresh(new_file)
        return new_file

    async def get_node_by_id(self, user_id: int, node_id: int) -> Optional[UserFileDO]:
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.id == node_id,
            UserFileDO.is_active == "Y",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_node(self, user_id: int, node_id: int) -> bool:
        """Soft-delete a file or folder (recursive for folders).

        For a single file:
        - Sets is_active="N", deleted_root_id=node.id.
        - Creates one RecycleFileDO entry.

        For a folder:
        - Recursively gathers all active descendants via list_recursive.
        - Sets is_active="N" and deleted_root_id=node.id on every descendant
          that was not already independently soft-deleted (only active rows are
          touched, so prior independent deletes keep their own deleted_root_id).
        - Sets is_active="N" and deleted_root_id=node.id on the folder itself.
        - Creates a single RecycleFileDO entry for the folder root whose size
          is the sum of all active descendant file sizes (for accurate recycle
          usage reporting).
        """
        node = await self.get_node_by_id(user_id, node_id)
        if not node:
            return False

        now_ms = int(time.time() * 1000)

        if node.is_folder == "Y":
            # Gather all currently-active descendants.
            descendants = await self.list_recursive(user_id, node.id)
            subtree_size = 0
            for desc_node, _rel_path in descendants:
                # list_recursive only returns active nodes (uses list_directory which
                # filters is_active="Y"), so every node here is fair game.
                desc_node.is_active = "N"
                desc_node.deleted_root_id = node.id
                if desc_node.is_folder == "N":
                    subtree_size += desc_node.size or 0

            # Soft-delete the folder root itself.
            node.is_active = "N"
            node.deleted_root_id = node.id

            recycle = RecycleFileDO(
                user_id=user_id,
                file_id=node.id,
                file_name=node.file_name,
                size=subtree_size,
                is_folder=node.is_folder,
                delete_time=now_ms,
            )
        else:
            node.is_active = "N"
            node.deleted_root_id = node.id

            recycle = RecycleFileDO(
                user_id=user_id,
                file_id=node.id,
                file_name=node.file_name,
                size=node.size,
                is_folder=node.is_folder,
                delete_time=now_ms,
            )

        self.db.add(recycle)
        await self.db.commit()
        return True

    async def resolve_path(self, user_id: int, path: str) -> UserFileDO | None:
        """Resolve a posix-style path to a file node."""
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            # Root? We don't have a root node in DB usually (directory_id=0 implies root children)
            # Retuning None might be ambiguous if we expected a node.
            # But technically root doesn't exist as a UserFileDO record.
            return None

        current_dir_id = 0
        current_node = None

        for part in parts:
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == current_dir_id,
                UserFileDO.file_name == part,
                UserFileDO.is_active == "Y",
            )
            result = await self.db.execute(stmt)
            if (node := result.scalar_one_or_none()) is None:
                return None

            current_node = node
            if node.is_folder == "Y":
                current_dir_id = node.id

        return current_node

    async def get_full_path(self, user_id: int, node_id: int) -> str:
        """Resolve the full path of a node by walking up the directory tree."""
        if node_id == 0:
            return ""

        path_parts: list[str] = []
        current_id = node_id

        # Loop until root (0) or not found.
        # Check for circular refs? Simple depth limit could work if needed.
        depth = 0
        max_depth = 50

        while current_id != 0 and depth < max_depth:
            node = await self.get_node_by_id(user_id, current_id)
            if not node:
                # If node is missing mid-tree, we might have a broken tree or root
                # Just return what we have? or broken?
                break

            path_parts.insert(0, node.file_name)
            current_id = node.directory_id
            depth += 1

        return "/".join(path_parts)

    async def ensure_directory_path(self, user_id: int, path: str) -> int:
        """Ensure a directory path exists, creating if necessary. Returns the final directory ID."""
        parts = [p for p in path.strip("/").split("/") if p]
        current_dir_id = 0

        for part in parts:
            stmt = select(UserFileDO).where(
                UserFileDO.user_id == user_id,
                UserFileDO.directory_id == current_dir_id,
                UserFileDO.file_name == part,
                UserFileDO.is_active == "Y",
            )
            result = await self.db.execute(stmt)
            if node := result.scalar_one_or_none():
                if node.is_folder != "Y":
                    raise InvalidPath(f"{part} is a file")
                current_dir_id = node.id
            else:
                # Note: This could likely be made more efficient creating multiple
                # directories in a single transaction.
                new_dir = await self.create_directory(user_id, current_dir_id, part)
                current_dir_id = new_dir.id

        return current_dir_id

    async def move_node(
        self,
        user_id: int,
        node_id: int,
        new_parent_id: int,
        new_name: str,
        autorename: bool = False,
    ) -> UserFileDO | None:
        """Move a node to a new directory."""
        node = await self.get_node_by_id(user_id, node_id)
        if not node:
            return None

        # Cyclic check: ensure new_parent is not a descendant of node
        if node.is_folder == "Y":
            curr_id = new_parent_id
            visited = set()
            while curr_id != 0:
                if curr_id == node.id:
                    raise InvalidPath(
                        "Cyclic move: cannot move a folder into itself or its descendants"
                    )
                if curr_id in visited:
                    raise InvalidPath(
                        f"Cycle detected in move {node_id} -> {new_parent_id} found {curr_id} multiple times"
                    )
                visited.add(curr_id)
                stmt = select(UserFileDO.directory_id).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.id == curr_id,
                    UserFileDO.is_active == "Y",
                )
                res = await self.db.execute(stmt)
                curr_id = res.scalar() or 0

        # Identity check: if same parent and same name, it's a no-op UNLESS autorename is True
        if (
            not autorename
            and node.directory_id == new_parent_id
            and node.file_name == new_name
        ):
            return node

        # Validate destination
        if new_parent_id != 0:
            parent = await self.get_node_by_id(user_id, new_parent_id)
            if not parent or parent.is_folder == "N":
                raise InvalidPath(
                    f"Invalid destination: folder {new_parent_id} not found"
                )

        # Collision resolution
        if autorename:
            logger.debug("Autorename enabled for move")
            base_name = new_name
            ext = ""
            if "." in base_name and not node.is_folder == "Y":
                parts = base_name.rsplit(".", 1)
                base_name = parts[0]
                ext = f".{parts[1]}"

            counter = 1
            while await self._check_exists(
                user_id, new_parent_id, new_name, node.is_folder
            ):
                new_name = f"{base_name} ({counter}){ext}"
                counter += 1
                if counter > 100:
                    raise FileAlreadyExists(f"File already exists: {new_name}")
        elif await self._check_exists(user_id, new_parent_id, new_name, node.is_folder):
            raise FileAlreadyExists(f"File already exists: {new_name}")

        node.directory_id = new_parent_id
        node.file_name = new_name
        node.update_time = int(time.time() * 1000)

        await self.db.commit()
        return node

    async def copy_node(
        self,
        user_id: int,
        source_node_id: int,
        new_parent_id: int,
        autorename: bool,
        new_name: str,
    ) -> UserFileDO | None:
        """Copy a node recursively."""
        source_node = await self.get_node_by_id(user_id, source_node_id)
        if not source_node:
            return None

        # Collision resolution for the root of the copy
        if autorename:
            logger.debug("Autorename enabled for copy")
            base_name = new_name
            ext = ""
            if "." in base_name and not source_node.is_folder == "Y":
                parts = base_name.rsplit(".", 1)
                base_name = parts[0]
                ext = f".{parts[1]}"

            counter = 1
            while await self._check_exists(
                user_id, new_parent_id, new_name, source_node.is_folder
            ):
                new_name = f"{base_name}({counter}){ext}"
                counter += 1
                if counter > 100:
                    raise FileAlreadyExists(f"File already exists: {new_name}")
        elif await self._check_exists(
            user_id, new_parent_id, new_name, source_node.is_folder
        ):
            raise FileAlreadyExists(f"File already exists: {new_name}")

        now_ms = int(time.time() * 1000)
        new_node = UserFileDO(
            user_id=user_id,
            directory_id=new_parent_id,
            file_name=new_name,
            is_folder=source_node.is_folder,
            size=source_node.size,
            md5=source_node.md5,
            storage_key=source_node.storage_key,
            create_time=now_ms,
            update_time=now_ms,
            is_active="Y",
        )
        self.db.add(new_node)
        await self.db.commit()
        await self.db.refresh(new_node)

        # Recursive copy for folders
        if source_node.is_folder == "Y":
            children = await self.list_directory(user_id, source_node_id)
            for child in children:
                await self.copy_node(
                    user_id=user_id,
                    source_node_id=child.id,
                    new_parent_id=new_node.id,
                    autorename=False,  # Children names are copied exactly within the new folder
                    new_name=child.file_name,
                )

        return new_node

    async def list_recycle(self, user_id: int) -> list[RecycleFileDO]:
        """List files in recycle bin."""
        stmt = select(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def restore_node(self, user_id: int, recycle_id: int) -> bool:
        """Restore a file or folder subtree from the recycle bin.

        For a single file:
        - Reactivates the one UserFileDO row, auto-renaming if the path is now occupied.

        For a folder:
        - Reactivates the folder root and all UserFileDO rows sharing the same
          deleted_root_id (i.e. all members of the deleted subtree).
        - Auto-renames the root only; descendants live inside the restored subtree
          and cannot have sibling collisions caused by the restore.
        - Clears deleted_root_id on every reactivated row.
        - Removes the single RecycleFileDO entry.

        Orphan guard (restore-to-root fallback):
        - If the item's original parent folder no longer exists or is inactive, the
          root is reparented to directory_id=0 (root) so it always surfaces in the
          file tree rather than becoming invisible under a deleted parent.
        - Only the root is reparented; folder-subtree descendants keep their
          intra-subtree directory_ids and are never orphaned by this case.
        """
        stmt = select(RecycleFileDO).where(
            RecycleFileDO.user_id == user_id, RecycleFileDO.id == recycle_id
        )
        result = await self.db.execute(stmt)
        if (recycle_entry := result.scalar_one_or_none()) is None:
            return False

        root_file_id = recycle_entry.file_id
        now_ms = int(time.time() * 1000)

        # Gather the root node.
        node_stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id, UserFileDO.id == root_file_id
        )
        node_result = await self.db.execute(node_stmt)
        root_node = node_result.scalar_one_or_none()

        if root_node is not None:
            # Orphan guard: verify the original parent is still active.
            # If it's gone, fall back to root so the item is always browsable.
            target_parent_id = root_node.directory_id
            if target_parent_id != 0:
                parent = await self.get_node_by_id(user_id, target_parent_id)
                if parent is None or parent.is_folder != "Y":
                    target_parent_id = 0

            # Resolve name collision against the effective parent.
            root_node.file_name = await self._resolve_unique_name(
                user_id, target_parent_id, root_node.file_name, root_node.is_folder
            )
            root_node.directory_id = target_parent_id
            root_node.is_active = "Y"
            root_node.deleted_root_id = None
            root_node.update_time = now_ms

            if root_node.is_folder == "Y":
                # Reactivate all other members of this deleted subtree.
                subtree_stmt = select(UserFileDO).where(
                    UserFileDO.user_id == user_id,
                    UserFileDO.deleted_root_id == root_file_id,
                    UserFileDO.id != root_file_id,  # root already handled above
                )
                subtree_result = await self.db.execute(subtree_stmt)
                for member in subtree_result.scalars().all():
                    member.is_active = "Y"
                    member.deleted_root_id = None
                    member.update_time = now_ms

        await self.db.delete(recycle_entry)
        await self.db.commit()
        return True

    async def purge_recycle(
        self, user_id: int, recycle_ids: list[int] | None = None
    ) -> list[str]:
        """Permanently delete items from recycle bin.

        Removes the RecycleFileDO entries and all UserFileDO rows that belong to
        the deleted subtree — identified via deleted_root_id == entry.file_id.
        For single-file entries, deleted_root_id == the file's own id, so the same
        logic applies uniformly.

        Returns a list of storage_keys that are now unreferenced by any UserFileDO
        row (active or inactive). The caller is responsible for deleting those blobs.
        The ref-count check is performed after deletion so the count is accurate —
        copy_node shares storage_keys, so a key is only returned when truly orphaned.
        """
        # Step 1: Collect the RecycleFileDO entries to purge.
        entry_stmt = select(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
        if recycle_ids:
            entry_stmt = entry_stmt.where(RecycleFileDO.id.in_(recycle_ids))
        result = await self.db.execute(entry_stmt)
        entries = list(result.scalars().all())

        if not entries:
            return []

        root_file_ids = [e.file_id for e in entries]

        # Step 2: Collect all UserFileDO rows belonging to these subtrees.
        # For single files: deleted_root_id == file's own id.
        # For folder subtrees: all members share deleted_root_id == folder root id.
        subtree_stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.deleted_root_id.in_(root_file_ids),
        )
        subtree_result = await self.db.execute(subtree_stmt)
        all_nodes = list(subtree_result.scalars().all())

        # Collect storage keys from non-folder rows only (folders have no blob).
        candidate_keys = [
            n.storage_key for n in all_nodes
            if n.is_folder == "N" and n.storage_key
        ]

        # Step 3: Delete all UserFileDO rows in the subtrees.
        for node in all_nodes:
            await self.db.delete(node)

        # Step 4: Delete RecycleFileDO entries.
        del_stmt = delete(RecycleFileDO).where(RecycleFileDO.user_id == user_id)
        if recycle_ids:
            del_stmt = del_stmt.where(RecycleFileDO.id.in_(recycle_ids))
        await self.db.execute(del_stmt)

        # Step 5: Commit – rows are gone now.
        await self.db.commit()

        # Step 6: For each candidate key, check remaining refs.
        # A key is orphaned only when no UserFileDO row (any state) still references it.
        # copy_node shares storage_keys, so we must be careful not to remove a live blob.
        orphaned_keys: list[str] = []
        for key in set(candidate_keys):
            ref_stmt = select(func.count(UserFileDO.id)).where(
                UserFileDO.storage_key == key
            )
            ref_result = await self.db.execute(ref_stmt)
            count = ref_result.scalar() or 0
            if count == 0:
                orphaned_keys.append(key)

        return orphaned_keys

    async def search_files(self, user_id: int, keyword: str) -> list[UserFileDO]:
        """Search for active files/folders by keyword (case-insensitive)."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
            UserFileDO.file_name.ilike(f"%{keyword}%"),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _check_exists(
        self,
        user_id: int,
        parent_id: int,
        name: str,
        is_folder: str,
    ) -> bool:
        """Check if a node exists with the given name in the parent directory."""
        stmt = select(UserFileDO).where(
            UserFileDO.user_id == user_id,
            UserFileDO.directory_id == parent_id,
            UserFileDO.file_name == name,
            UserFileDO.is_active == "Y",
        )
        if is_folder is not None:
            stmt = stmt.where(UserFileDO.is_folder == is_folder)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _resolve_unique_name(
        self, user_id: int, parent_id: int, name: str, is_folder: str
    ) -> str:
        """Return a name that does not collide with any active node in the parent directory.

        If *name* is already free, returns it unchanged.  Otherwise appends
        ``(1)``, ``(2)`` … preserving any file extension (for non-folders).
        Raises ``FileAlreadyExists`` after 100 attempts.
        """
        if not await self._check_exists(user_id, parent_id, name, is_folder):
            return name

        base_name = name
        ext = ""
        if is_folder != "Y" and "." in name:
            base_name, raw_ext = name.rsplit(".", 1)
            ext = f".{raw_ext}"

        for counter in range(1, 101):
            candidate = f"{base_name} ({counter}){ext}"
            if not await self._check_exists(user_id, parent_id, candidate, is_folder):
                return candidate

        raise FileAlreadyExists(f"File already exists: {name}")

    async def get_aggregated_folder_sizes(self, user_id: int) -> dict[int, int]:
        """Return a map of folder_id -> total descendant file bytes for all folders owned by user."""
        stmt = select(
            UserFileDO.id,
            UserFileDO.directory_id,
            UserFileDO.is_folder,
            UserFileDO.size,
        ).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
        )
        rows = (await self.db.execute(stmt)).all()

        children: dict[int, list] = {}
        for r in rows:
            children.setdefault(r.directory_id, []).append(r)

        sizes: dict[int, int] = {}

        def dfs(folder_id: int) -> int:
            total = 0
            for c in children.get(folder_id, []):
                total += dfs(c.id) if c.is_folder == "Y" else (c.size or 0)
            sizes[folder_id] = total
            return total

        for r in rows:
            if r.is_folder == "Y" and r.id not in sizes:
                dfs(r.id)

        return sizes

    async def get_total_usage(self, user_id: int) -> int:
        """Calculate total storage usage for a user in bytes."""
        stmt = select(func.sum(UserFileDO.size)).where(
            UserFileDO.user_id == user_id,
            UserFileDO.is_active == "Y",
            UserFileDO.is_folder == "N",
        )
        result = await self.db.execute(stmt)
        total = result.scalar()
        return total or 0

    async def get_recycle_usage(self, user_id: int) -> int:
        """Calculate total size of files in the recycle bin for a user in bytes."""
        stmt = select(func.sum(RecycleFileDO.size)).where(
            RecycleFileDO.user_id == user_id
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def is_empty(self, user_id: int) -> bool:
        """Check whether the user has any active *files* on the server.

        Folders are intentionally excluded. This result drives the sync
        ``synType`` flag (``synType = not is_empty``):

        - ``synType=False`` -> initialization mode (device uploads to server)
        - ``synType=True``  -> differential sync (server data is authoritative)

        If we counted folders here, a server that holds only the default
        folder skeleton (e.g. after a fresh init sync that created folders but
        no files yet) would report non-empty, flip ``synType`` to ``True``, and
        the device would interpret its missing files as remote deletions and
        wipe them locally. Counting only files keeps a file-less server in the
        safe initialization mode.
        """
        # Use limit 1 for efficiency
        stmt = (
            select(UserFileDO.id)
            .where(
                UserFileDO.user_id == user_id,
                UserFileDO.is_active == "Y",
                UserFileDO.is_folder == "N",
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.first() is None
