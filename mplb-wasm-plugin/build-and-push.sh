#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
REPO_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
IMAGE_REPOSITORY="ghcr.io/talha-waheed/mplb-plugin"
TAG_SUFFIX="lb4-${REPO_COMMIT:0:12}"
PUSH=false
STRATEGIES=(
    "nodal_leastrequest"
    "nodal_leastrequest_rlpb"
    "leastrequest_plus_rlpb"
)

usage() {
    cat <<'EOF'
Usage: build-and-push.sh [options]

Build immutable WASM images without modifying main.go or wasm-out/.

Options:
  --push                  Push each image after building it.
  --repository REPOSITORY Override the image repository.
  --tag-suffix SUFFIX     Override lb4-<12-character-git-commit>.
  --strategies CSV        Build a comma-separated strategy subset.
  -h, --help              Show this help.
EOF
}

while (($#)); do
    case "$1" in
        --push)
            PUSH=true
            shift
            ;;
        --repository)
            IMAGE_REPOSITORY="$2"
            shift 2
            ;;
        --tag-suffix)
            TAG_SUFFIX="$2"
            shift 2
            ;;
        --strategies)
            IFS=',' read -r -a STRATEGIES <<< "$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ((${#STRATEGIES[@]} == 0)); then
    echo "No load-balancing strategies selected" >&2
    exit 2
fi
if [[ ! "$TAG_SUFFIX" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    echo "Invalid image tag suffix: $TAG_SUFFIX" >&2
    exit 2
fi

for strategy in "${STRATEGIES[@]}"; do
    if [[ ! "$strategy" =~ ^[a-z0-9_]+$ ]]; then
        echo "Invalid load-balancing strategy: $strategy" >&2
        exit 2
    fi
done

TINYGO_BIN="${TINYGO_BIN:-$(command -v tinygo || true)}"
if [[ -z "$TINYGO_BIN" ]]; then
    echo "tinygo is not installed or is not on PATH" >&2
    exit 1
fi

if docker info >/dev/null 2>&1; then
    DOCKER_CMD=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
    DOCKER_CONFIG_PATH="${DOCKER_CONFIG:-${HOME}/.docker}"
    DOCKER_CMD=(sudo -n env "DOCKER_CONFIG=$DOCKER_CONFIG_PATH" docker)
else
    echo "Docker is not accessible directly or through passwordless sudo" >&2
    exit 1
fi

BUILD_DIR="$(mktemp -d "$SCRIPT_DIR/.build-tmp.XXXXXX")"
cleanup() {
    rm -rf -- "$BUILD_DIR"
}
trap cleanup EXIT

cp "$SCRIPT_DIR"/*.go "$SCRIPT_DIR"/go.mod "$SCRIPT_DIR"/go.sum \
    "$SCRIPT_DIR"/Dockerfile "$BUILD_DIR"/
mkdir -p "$BUILD_DIR/wasm-out"

echo "Source commit: $REPO_COMMIT"
echo "Tag suffix: $TAG_SUFFIX"

for strategy in "${STRATEGIES[@]}"; do
    image="$IMAGE_REPOSITORY:$strategy-$TAG_SUFFIX"
    sed -E -i \
        "s/(LOAD_BALANCING_STRATEGY = ).*/\\1\"$strategy\"/" \
        "$BUILD_DIR/main.go"

    echo "Building $image"
    (
        cd "$BUILD_DIR"
        GOARCH=wasm GOOS=js "$TINYGO_BIN" build \
            -o wasm-out/slate_plugin.wasm \
            -gc=custom \
            -tags="custommalloc nottinygc_envoy" \
            -scheduler=none \
            -target=wasi \
            .
    )
    "${DOCKER_CMD[@]}" build -t "$image" "$BUILD_DIR"

    if [[ "$PUSH" == true ]]; then
        "${DOCKER_CMD[@]}" push "$image"
    fi
done

echo "Completed ${#STRATEGIES[@]} immutable image build(s)."
