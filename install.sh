#!/bin/sh

usage() {
    printf 'Usage: install.sh [repository-directory]\n       install.sh --help\n'
}
fail() {
    printf 'install.sh: %s\n' "$1" >&2
    exit 1
}

show_help=0
target_arg=
operands=0
options=1
for arg do
    if [ "$options" -eq 1 ]; then
        case $arg in
            --) options=0; continue ;;
            -h|--help) show_help=1; continue ;;
            -*) usage >&2; exit 2 ;;
        esac
        options=0
    fi
    operands=$((operands + 1))
    target_arg=$arg
done
if [ "$show_help" -eq 1 ]; then
    [ "$operands" -eq 0 ] || { usage >&2; exit 2; }
    usage
    exit 0
fi
[ "$operands" -le 1 ] || { usage >&2; exit 2; }

script_dir=$(CDPATH= cd -P "$(dirname "$0")" 2>/dev/null && pwd) || fail "cannot locate installer directory"
source_launcher=$script_dir/concordw
source_properties=$script_dir/.concord/wrapper/concord-wrapper.properties
[ -f "$source_launcher" ] && [ -r "$source_launcher" ] || fail "cannot read bundled launcher: $source_launcher"
[ -f "$source_properties" ] && [ -r "$source_properties" ] || fail "cannot read bundled properties: $source_properties"
[ -n "$target_arg" ] || target_arg=.
[ -d "$target_arg" ] || fail "target is not an existing directory: $target_arg"
target=$(CDPATH= cd -P "$target_arg" 2>/dev/null && pwd) || fail "cannot resolve target directory: $target_arg"
launcher_dest=$target/concordw
concord_dir=$target/.concord
wrapper_dir=$concord_dir/wrapper
properties_dest=$wrapper_dir/concord-wrapper.properties

for path in "$launcher_dest" "$properties_dest"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
        fail "destination already exists: $path"
    fi
done
for path in "$concord_dir" "$wrapper_dir"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
        [ -d "$path" ] && [ ! -L "$path" ] || fail "destination component is not an ordinary directory: $path"
    fi
done

created_launcher=0
created_properties=0
launcher_stage=
properties_stage=
cleanup() {
    status=$?
    trap - 0 HUP INT TERM
    if [ "$status" -ne 0 ]; then
        [ "$created_launcher" -eq 0 ] || rm -f "$launcher_dest"
        [ "$created_properties" -eq 0 ] || rm -f "$properties_dest"
    fi
    [ -z "$launcher_stage" ] || rm -rf "$launcher_stage"
    [ -z "$properties_stage" ] || rm -rf "$properties_stage"
    exit "$status"
}
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ ! -d "$concord_dir" ]; then mkdir "$concord_dir" 2>/dev/null || fail "cannot create directory: $concord_dir"; fi
if [ ! -d "$wrapper_dir" ]; then mkdir "$wrapper_dir" 2>/dev/null || fail "cannot create directory: $wrapper_dir"; fi
properties_stage=$(mktemp -d "$wrapper_dir/.install.XXXXXX") || fail "cannot stage properties in $wrapper_dir"
launcher_stage=$(mktemp -d "$target/.install.XXXXXX") || fail "cannot stage launcher in $target"
cp "$source_properties" "$properties_stage/concord-wrapper.properties" || fail "cannot stage properties"
cp "$source_launcher" "$launcher_stage/concordw" || fail "cannot stage launcher"
chmod 0644 "$properties_stage/concord-wrapper.properties" || fail "cannot set properties mode"
chmod 0755 "$launcher_stage/concordw" || fail "cannot set launcher mode"
ln "$properties_stage/concord-wrapper.properties" "$properties_dest" || fail "cannot publish properties: $properties_dest"
created_properties=1
ln "$launcher_stage/concordw" "$launcher_dest" || fail "cannot publish launcher: $launcher_dest"
created_launcher=1
rm -rf "$launcher_stage" "$properties_stage" || fail "cannot remove staging directories"
launcher_stage=
properties_stage=
printf 'Installed %s\nInstalled %s\nRun from %s: ./concordw --version\n' "$launcher_dest" "$properties_dest" "$target"
exit 0
