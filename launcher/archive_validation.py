"""Validation for source archives before Launcher extraction."""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


class ArchiveValidationError(Exception):
    """Raised when a source archive is not safe to extract."""


@dataclass(frozen=True)
class ZipMemberPlan:
    info: zipfile.ZipInfo
    parts: tuple[str, ...]
    kind: str
    symlink_target: str | None = None


def validate_source_archive(archive_path: Path) -> None:
    """Validate that a source archive can be safely extracted by Launcher."""
    if archive_path.suffix != ".zip":
        raise ArchiveValidationError("Only .zip source archives are supported")

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            infos = zf.infolist()
            validate_zip_members(infos)
            root_folder = single_archive_root(infos)
            plan = build_zip_member_plan(zf, infos, root_folder)
            validate_zip_symlinks(plan)
    except zipfile.BadZipFile as e:
        raise ArchiveValidationError(f"Invalid zip archive: {e}") from e


def validate_zip_members(infos: list[zipfile.ZipInfo]) -> None:
    """Reject archive members that could write outside the extraction tree."""
    for info in infos:
        name = info.filename
        if not name:
            raise ArchiveValidationError("Archive contains an empty path")
        if "\\" in name:
            raise ArchiveValidationError(f"Archive contains unsafe path: {name}")

        path = PurePosixPath(name)
        windows_path = PureWindowsPath(name)
        if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
            raise ArchiveValidationError(f"Archive contains absolute path: {name}")
        if any(part == ".." for part in path.parts):
            raise ArchiveValidationError(f"Archive contains parent path segment: {name}")

        file_type = (info.external_attr >> 16) & 0o170000
        if file_type:
            if not (stat.S_ISLNK(file_type) or stat.S_ISDIR(file_type) or stat.S_ISREG(file_type)):
                raise ArchiveValidationError(f"Archive contains special file: {name}")


def single_archive_root(infos: list[zipfile.ZipInfo]) -> str | None:
    roots = {
        PurePosixPath(info.filename).parts[0]
        for info in infos
        if PurePosixPath(info.filename).parts
    }
    return next(iter(roots)) if len(roots) == 1 else None


def build_zip_member_plan(
    zf: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    root_folder: str | None,
) -> list[ZipMemberPlan]:
    plan = []
    seen_paths = set()

    for info in infos:
        parts = list(PurePosixPath(info.filename).parts)
        if root_folder and parts and parts[0] == root_folder:
            parts = parts[1:]
        if not parts:
            continue

        parts_tuple = tuple(parts)
        if parts_tuple in seen_paths:
            raise ArchiveValidationError(f"Archive contains duplicate path: {info.filename}")
        seen_paths.add(parts_tuple)

        kind = zip_member_kind(info)
        symlink_target = read_zip_symlink_target(zf, info) if kind == "symlink" else None
        plan.append(ZipMemberPlan(info=info, parts=parts_tuple, kind=kind, symlink_target=symlink_target))

    validate_no_file_or_symlink_children(plan)
    return plan


def zip_member_kind(info: zipfile.ZipInfo) -> str:
    if info.is_dir():
        return "dir"
    if is_zip_symlink(info):
        return "symlink"
    return "file"


def validate_no_file_or_symlink_children(plan: list[ZipMemberPlan]) -> None:
    blocking_paths = {member.parts for member in plan if member.kind in {"file", "symlink"}}
    for member in plan:
        for index in range(1, len(member.parts)):
            parent = member.parts[:index]
            if parent in blocking_paths:
                raise ArchiveValidationError(
                    f"Archive contains child entries under file or symlink: {'/'.join(parent)}"
                )


def validate_zip_symlinks(plan: list[ZipMemberPlan]) -> None:
    members = {member.parts: member for member in plan}
    directories = {
        member.parts[:index]
        for member in plan
        for index in range(1, len(member.parts))
    }

    for member in plan:
        if member.kind != "symlink":
            continue
        target_parts = normalize_symlink_target(member.parts, member.symlink_target or "")
        if target_parts is None:
            raise ArchiveValidationError(
                f"Archive contains unsafe symlink target: {member.info.filename} -> {member.symlink_target}"
            )
        resolve_zip_symlink_target(member.parts, target_parts, members, directories, set())


def normalize_symlink_target(link_parts: tuple[str, ...], target: str) -> tuple[str, ...] | None:
    if "\\" in target:
        return None

    target_path = PurePosixPath(target)
    windows_target = PureWindowsPath(target)
    if target_path.is_absolute() or windows_target.is_absolute() or windows_target.drive:
        return None

    resolved_parts = list(link_parts[:-1])
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved_parts:
                return None
            resolved_parts.pop()
            continue
        resolved_parts.append(part)

    return tuple(resolved_parts)


def resolve_zip_symlink_target(
    link_parts: tuple[str, ...],
    target_parts: tuple[str, ...],
    members: dict[tuple[str, ...], ZipMemberPlan],
    directories: set[tuple[str, ...]],
    seen: set[tuple[str, ...]],
) -> None:
    if target_parts in directories and target_parts not in members:
        return

    target_member = members.get(target_parts)
    if target_member is None:
        raise ArchiveValidationError(f"Archive contains dangling symlink: {'/'.join(link_parts)}")

    if target_member.kind != "symlink":
        return

    if target_parts in seen:
        raise ArchiveValidationError(f"Archive contains cyclic symlink: {'/'.join(link_parts)}")
    seen.add(target_parts)

    next_target = normalize_symlink_target(target_member.parts, target_member.symlink_target or "")
    if next_target is None:
        raise ArchiveValidationError(
            f"Archive contains unsafe symlink target: {target_member.info.filename} -> "
            f"{target_member.symlink_target}"
        )
    resolve_zip_symlink_target(link_parts, next_target, members, directories, seen)


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    file_type = (info.external_attr >> 16) & 0o170000
    return stat.S_ISLNK(file_type)


def read_zip_symlink_target(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    try:
        target = zf.read(info).decode("utf-8")
    except UnicodeDecodeError as e:
        raise ArchiveValidationError(f"Archive contains undecodable symlink target: {info.filename}") from e
    if not target:
        raise ArchiveValidationError(f"Archive contains empty symlink target: {info.filename}")
    return target
