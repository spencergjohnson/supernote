# Build args — override at build time:
#   CUDA_ARCH   CUDA compute capability (default 86 = Ampere / RTX 30xx).
#               Common values: 75=Turing/20xx, 86=Ampere/30xx, 89=Ada/40xx, 120=Blackwell/50xx.
#   LLAMA_SWAP_REF / LLAMA_CPP_REF  git ref to clone (default: HEAD of default branch).
ARG CUDA_ARCH=86
ARG LLAMA_SWAP_REF=HEAD
ARG LLAMA_CPP_REF=HEAD

FROM node:22 AS ui-builder
ARG LLAMA_SWAP_REF
RUN git clone https://github.com/mostlygeek/llama-swap.git /src && \
    if [ "$LLAMA_SWAP_REF" != "HEAD" ]; then git -C /src checkout "$LLAMA_SWAP_REF"; fi
WORKDIR /src/ui-svelte
RUN npm install && npm run build

FROM golang:1.26 AS go-builder
COPY --from=ui-builder /src /src
WORKDIR /src
RUN go build -o build/llama-swap .

FROM nvidia/cuda:12.6.3-devel-ubuntu24.04 AS llama-builder
ARG CUDA_ARCH
ARG LLAMA_CPP_REF
RUN apt-get update && apt-get install -y cmake build-essential curl git libcurl4-openssl-dev
RUN git clone https://github.com/ggml-org/llama.cpp /llama && \
    if [ "$LLAMA_CPP_REF" != "HEAD" ]; then git -C /llama checkout "$LLAMA_CPP_REF"; fi && \
    cmake /llama -B /llama/build \
      -DGGML_CUDA=ON \
      -DBUILD_SHARED_LIBS=OFF \
      -DLLAMA_CURL=ON \
      -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCH}" && \
    cmake --build /llama/build --config Release -j$(nproc) --target llama-server

FROM nvidia/cuda:12.6.3-runtime-ubuntu24.04
RUN apt-get update && apt-get install -y libcurl4 curl libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=llama-builder /llama/build/bin/llama-server /app/llama-server
COPY --from=go-builder /src/build/llama-swap /app/llama-swap
ENTRYPOINT ["/app/llama-swap"]
