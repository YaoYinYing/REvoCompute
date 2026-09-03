# AlphaFold 3 source and dependency lock pinned to upstream revision c0f97eda.
FROM alpine/git:2.47.2 AS alphafold3-source
ARG ALPHAFOLD3_REPO=https://github.com/google-deepmind/alphafold3.git
ARG ALPHAFOLD3_REF=c0f97eda2f1f482fd94d3a38bece18c7069b4a5c
RUN git init /app/alphafold && git -C /app/alphafold remote add origin ${ALPHAFOLD3_REPO} && \
    git -C /app/alphafold fetch --depth 1 origin ${ALPHAFOLD3_REF} && \
    git -C /app/alphafold checkout --detach FETCH_HEAD && rm -rf /app/alphafold/.git

FROM nvidia/cuda:12.6.3-base-ubuntu24.04

ARG RUNNER_UID ARG RUNNER_GID ARG RUNNER_USERNAME ARG RUNNER_GROUP

RUN DEBIAN_FRONTEND=noninteractive apt-get update --quiet && \
    apt-get install --yes --quiet --no-install-recommends python3.12 python3.12-dev git wget gcc g++ make zlib1g-dev zstd ca-certificates patch && \
    rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/alphafold3_venv
RUN uv venv ${UV_PROJECT_ENVIRONMENT}
ENV PATH="/hmmer/bin:/alphafold3_venv/bin:${PATH}"

COPY --from=alphafold3-source /app/alphafold/docker/jackhmmer_seq_limit.patch /tmp/jackhmmer_seq_limit.patch
RUN mkdir /hmmer_build /hmmer && \
    wget -q http://eddylab.org/software/hmmer/hmmer-3.4.tar.gz -P /hmmer_build && \
    cd /hmmer_build && echo "ca70d94fd0cf271bd7063423aabb116d42de533117343a9b27a65c17ff06fbf3 hmmer-3.4.tar.gz" | sha256sum --check && \
    tar zxf hmmer-3.4.tar.gz && patch -p0 < /tmp/jackhmmer_seq_limit.patch && \
    cd hmmer-3.4 && ./configure --prefix=/hmmer && make -j && make install && cd easel && make install && \
    rm -rf /hmmer_build /tmp/jackhmmer_seq_limit.patch

COPY --from=alphafold3-source /app/alphafold /app/alphafold
# Pin CMake FetchContent sources locally so the wheel build avoids nested clones.
RUN git clone --depth 1 https://github.com/pybind/pybind11 /opt/af3-deps/pybind11 && git -C /opt/af3-deps/pybind11 fetch --depth 1 origin 2e0815278cb899b20870a67ca8205996ef47e70f && git -C /opt/af3-deps/pybind11 checkout 2e0815278cb899b20870a67ca8205996ef47e70f
RUN git clone --depth 1 https://github.com/pybind/pybind11_abseil /opt/af3-deps/pybind11_abseil && git -C /opt/af3-deps/pybind11_abseil fetch --depth 1 origin bddf30141f9fec8e577f515313caec45f559d319 && git -C /opt/af3-deps/pybind11_abseil checkout bddf30141f9fec8e577f515313caec45f559d319 && \
    git clone --depth 1 https://github.com/abseil/abseil-cpp /opt/af3-deps/abseil-cpp && git -C /opt/af3-deps/abseil-cpp fetch --depth 1 origin d7aaad83b488fd62bd51c81ecf16cd938532cc0a && git -C /opt/af3-deps/abseil-cpp checkout d7aaad83b488fd62bd51c81ecf16cd938532cc0a && \
    git clone --depth 1 https://github.com/pdb-redo/libcifpp /opt/af3-deps/cifpp && git -C /opt/af3-deps/cifpp fetch --depth 1 origin ac98531a2fc8daf21131faa0c3d73766efa46180 && git -C /opt/af3-deps/cifpp checkout ac98531a2fc8daf21131faa0c3d73766efa46180 && \
    git clone --depth 1 https://github.com/PDB-REDO/dssp /opt/af3-deps/dssp && git -C /opt/af3-deps/dssp fetch --depth 1 origin 57560472b4260dc41f457706bc45fc6ef0bc0f10 && git -C /opt/af3-deps/dssp checkout 57560472b4260dc41f457706bc45fc6ef0bc0f10
WORKDIR /app/alphafold
RUN --mount=type=cache,target=/root/.cache/uv CMAKE_ARGS="-DFETCHCONTENT_SOURCE_DIR_PYBIND11=/opt/af3-deps/pybind11 -DFETCHCONTENT_SOURCE_DIR_PYBIND11_ABSEIL=/opt/af3-deps/pybind11_abseil -DFETCHCONTENT_SOURCE_DIR_ABSEIL_CPP=/opt/af3-deps/abseil-cpp -DFETCHCONTENT_SOURCE_DIR_CIFPP=/opt/af3-deps/cifpp -DFETCHCONTENT_SOURCE_DIR_DSSP=/opt/af3-deps/dssp" UV_LINK_MODE=copy uv sync --frozen --no-editable && \
    uv run build_data

RUN groupadd -f -r ${RUNNER_GROUP} -g ${RUNNER_GID} 2>/dev/null || true && \
    (id -u ${RUNNER_USERNAME} >/dev/null 2>&1 && usermod -u ${RUNNER_UID} -g ${RUNNER_GID} ${RUNNER_USERNAME}) || \
    useradd -o -r -g ${RUNNER_GROUP} -u ${RUNNER_UID} ${RUNNER_USERNAME}
RUN mkdir -p /app/revocompute && chown -R ${RUNNER_UID}:${RUNNER_GID} /app/revocompute /app/alphafold
COPY --chown=${RUNNER_UID}:${RUNNER_GID} ./docker/runners/alphafold3/run.sh ./docker/runners/common/task_context.sh ./docker/runners/common/task_context.py /app/revocompute/

ENV XLA_FLAGS="--xla_gpu_enable_triton_gemm=false" \
    XLA_PYTHON_CLIENT_PREALLOCATE=true \
    XLA_CLIENT_MEM_FRACTION=0.95 \
    RUNNER_USERNAME=${RUNNER_USERNAME}
ENV HTTP_PROXY="" HTTPS_PROXY="" ALL_PROXY="" \
    http_proxy="" https_proxy="" all_proxy="" NO_PROXY="" no_proxy=""
WORKDIR /app/revocompute
ENTRYPOINT ["bash", "/app/revocompute/run.sh"]
