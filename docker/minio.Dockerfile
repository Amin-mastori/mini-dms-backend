# syntax=docker/dockerfile:1
# The upstream October security release is source-only; build the exact commit.
FROM golang:1.26.7-bookworm AS build
WORKDIR /src
RUN git init && git remote add origin https://github.com/minio/minio.git \
    && git fetch --depth 1 origin 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a \
    && git checkout --detach FETCH_HEAD
ARG GOPROXY=direct
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOSUMDB=sum.golang.org GOCACHE=/go/build-cache
# Direct downloads avoid a mandatory module-proxy dependency. Keep verification enabled.
RUN --mount=type=cache,id=mini-dms-go-mod,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=mini-dms-go-build,target=/go/build-cache,sharing=locked \
    go build -mod=readonly -trimpath -o /out/minio . \
    && go mod verify
COPY docker/minio-healthcheck.go /healthcheck/main.go
RUN --mount=type=cache,id=mini-dms-go-mod,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,id=mini-dms-go-build,target=/go/build-cache,sharing=locked \
    go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/minio-healthcheck /healthcheck/main.go \
    && install -d -o 10001 -g 10001 /out/rootfs/data /out/rootfs/tmp

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build --chown=10001:10001 /out/rootfs/data /data
COPY --from=build --chown=10001:10001 /out/rootfs/tmp /tmp
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /out/minio-healthcheck /usr/local/bin/minio-healthcheck
COPY --from=build /src/LICENSE /usr/share/doc/minio/LICENSE
ENV HOME=/tmp
USER 10001:10001
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
