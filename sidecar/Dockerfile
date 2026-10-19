# The pilot-sync image: the store environment's sync sidecar, one static binary on scratch. It sets
# no USER: the pod's securityContext gives it the environment's uid, so the files it writes in the
# tree are the agent's to edit.

# The Go the sidecar's tests run on, here (`cexec go`) and in the Jenkinsfile's `Test sidecar`.
FROM registry:5000/kube-coder-go-toolchain:latest AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/pilot-sync ./cmd/pilot-sync

FROM scratch

# The sidecar speaks TLS to Pilot, whose certificate a public CA signs.
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/pilot-sync /pilot-sync

ENTRYPOINT ["/pilot-sync"]
