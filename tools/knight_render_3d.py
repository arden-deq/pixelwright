#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render a real, rigidly skinned Blender armature as image-generation guides.

blender --background --factory-startup --python tools/knight_render_3d.py -- \
    --out-dir runs/knight-3d/rig

Requires Blender only for guide creation. The exported metric rig, projected
joints, depth, normals and actual mesh part IDs remain ordinary JSON/PNG files.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import knight_rig_3d as rig

PART_NAMES = ["torso", "head", "upper_arm_r", "forearm_r", "mace", "upper_arm_l", "forearm_l",
              "shield", "thigh_r", "shin_r", "foot_r", "thigh_l", "shin_l", "foot_l"]
PART_COLORS = [(0, 0, 0), (130, 90, 210), (235, 70, 100), (255, 150, 45), (245, 220, 50),
               (235, 60, 200), (85, 190, 65), (80, 230, 145), (165, 110, 40),
               (70, 170, 230), (50, 220, 225), (245, 130, 70), (85, 90, 225),
               (140, 75, 210), (235, 90, 175)]


def bone_matrix(joints, a, b):
    y = rig.unit(joints[b] - joints[a])
    front = np.array((0.0, -1.0, 0.0))
    z = front - y * np.dot(front, y)
    if np.linalg.norm(z) < 1e-7:
        z = np.array((0.0, 0.0, 1.0)) - y * y[2]
    z = rig.unit(z)
    x = rig.unit(np.cross(y, z)); z = np.cross(x, y)
    matrix = Matrix.Identity(4)
    for col, value in enumerate((x, y, z, joints[a])):
        for row in range(3):
            matrix[row][col] = float(value[row])
    return matrix


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    return mat


def bind(obj, armature, bone, mat, part=None):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    obj.name = obj.name + "_" + bone
    obj.data.materials.append(mat)
    group = obj.vertex_groups.new(name=bone)
    group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    modifier = obj.modifiers.new("Rigid bone skin", "ARMATURE")
    modifier.object = armature
    obj["part_id"] = PART_NAMES.index(part or bone) + 1
    obj["bone"] = bone
    obj.select_set(False)
    return obj


def ellipsoid(name, armature, bone, center, scale, mat, part=None, rotation=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=1, location=tuple(center))
    obj = bpy.context.object; obj.name = name; obj.scale = scale
    if rotation is not None:
        obj.rotation_mode = "QUATERNION"; obj.rotation_quaternion = rotation
    return bind(obj, armature, bone, mat, part)


def box(name, armature, bone, center, scale, mat, part=None):
    bpy.ops.mesh.primitive_cube_add(size=2, location=tuple(center))
    obj = bpy.context.object; obj.name = name; obj.scale = scale
    return bind(obj, armature, bone, mat, part)


def along(name, armature, bone, joints, radius, mat, part=None, shorten=.92):
    a, b = (joints[n] for n in rig.BONES[bone])
    direction = Vector(b - a)
    return ellipsoid(name, armature, bone, (a + b) / 2,
                     (radius, radius * .86, direction.length * shorten / 2), mat, part,
                     direction.to_track_quat("Z", "Y"))


def shield_mesh(armature, center, mat, inset=1.0, y_offset=0.0):
    outline = [(-.23, .30), (.23, .30), (.21, -.02), (0, -.42), (-.21, -.02)]
    vertices = [(center[0] + x * inset, center[1] + dy + y_offset, center[2] + z * inset)
                for dy in (-.035, .035) for x, z in outline]
    faces = [tuple(range(4, -1, -1)), tuple(range(5, 10))]
    faces += [(i, (i + 1) % 5, (i + 1) % 5 + 5, i + 5) for i in range(5)]
    mesh = bpy.data.meshes.new("Kite mesh"); mesh.from_pydata(vertices, [], faces); mesh.update()
    obj = bpy.data.objects.new("Kite shield", mesh); bpy.context.collection.objects.link(obj)
    return bind(obj, armature, "shield", mat)


def create_scene(config=None, skeleton_only=False):
    config = config or rig.contract()
    camera_spec = config["camera"]
    bones = config["bones"]
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = config["frame_size"][0] * config["guide_scale"]
    scene.render.resolution_y = config["frame_size"][1] * config["guide_scale"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "BOTH"
    scene.display.shading.show_object_outline = True
    scene.display.render_aa = "16"
    scene.view_settings.view_transform = "Standard"
    camera_data = bpy.data.cameras.new("Fixed orthographic camera")
    camera_data.type = "ORTHO"; camera_data.ortho_scale = camera_spec["ortho_scale"]
    camera_data.clip_start = camera_spec["clip_start"]; camera_data.clip_end = camera_spec["clip_end"]
    camera = bpy.data.objects.new("Fixed orthographic camera", camera_data)
    scene.collection.objects.link(camera); scene.camera = camera
    camera.location = camera_spec["position"]
    camera.rotation_euler = (Vector(camera_spec["target"]) - camera.location).to_track_quat("-Z", "Y").to_euler()
    armature_data = bpy.data.armatures.new("Knight metric skeleton")
    armature = bpy.data.objects.new("Knight metric skeleton", armature_data)
    scene.collection.objects.link(armature); bpy.context.view_layer.objects.active = armature
    armature.select_set(True); bpy.ops.object.mode_set(mode="EDIT")
    rest = {n: np.asarray(v) for n, v in config["animations"]["block"]["frames"][0]["joints_world"].items()}
    for name, (a, b) in bones.items():
        bone = armature_data.edit_bones.new(name)
        # A newly allocated edit bone has zero length: assigning its matrix at
        # that point loses its orientation in Blender. Establish endpoints first.
        bone.head = tuple(rest[a]); bone.tail = tuple(rest[b])
        bone.align_roll(bone_matrix(rest, a, b).col[2].xyz)
    for name, parent in config["parents"].items():
        armature_data.edit_bones[name].parent = armature_data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT"); armature.select_set(False); armature.show_in_front = True
    for name, (a, b) in bones.items():
        bone = armature_data.bones[name]
        if max((bone.head_local - Vector(rest[a])).length,
               (bone.tail_local - Vector(rest[b])).length) > 1e-5:
            raise ValueError(f"Rest armature does not match world-space bone {name}")
    scene.render.fps = 30
    if skeleton_only:
        return scene, armature
    steel = material("Cool steel", (.43, .52, .62)); dark = material("Dark steel", (.075, .10, .145))
    red = material("Oxblood lacquer", (.43, .025, .05)); brass = material("Brass", (.64, .43, .15))
    brown = material("Leather", (.17, .075, .025)); black = material("Visor slit", (.008, .009, .016))
    silver = material("Mace steel", (.61, .68, .76))
    ellipsoid("Breastplate", armature, "torso", (0, 0, 1.31), (.275, .17, .35), steel)
    ellipsoid("Waist", armature, "torso", (0, 0, .98), (.23, .15, .105), brown)
    box("Buckle", armature, "torso", (0, -.155, .98), (.055, .025, .045), brass)
    # Stable skirt plates are attached to the same torso, rather than redrawn per pose.
    for x in (-.16, 0, .16):
        box("Fauld", armature, "torso", (x, -.08, .83), (.085, .13, .12), steel)
    ellipsoid("Gorget", armature, "head", (0, 0, 1.62), (.16, .135, .095), dark)
    box("Great helm", armature, "head", (0, -.015, 1.81), (.16, .145, .16), steel)
    box("Visor", armature, "head", (0, -.163, 1.84), (.135, .009, .025), black)
    box("Helm brass ridge", armature, "head", (0, -.176, 1.77), (.013, .012, .12), brass)
    for side in ("r", "l"):
        for segment, radius in (("upper_arm", .105), ("forearm", .085), ("thigh", .125), ("shin", .09)):
            bone = f"{segment}_{side}"
            along("Plate", armature, bone, rest, radius, steel)
        shoulder = rest[f"shoulder_{side}"]
        ellipsoid("Pauldron", armature, f"upper_arm_{side}", shoulder, (.15, .14, .13), steel)
        ellipsoid("Couter", armature, f"forearm_{side}", rest[f"elbow_{side}"], (.09, .09, .09), brass)
        ellipsoid("Gauntlet", armature, f"forearm_{side}", rest[f"hand_{side}"], (.085, .075, .09), steel)
        ellipsoid("Poleyn", armature, f"shin_{side}", rest[f"knee_{side}"], (.115, .10, .11), steel)
        ankle = rest[f"ankle_{side}"]
        box("Sabatons", armature, f"foot_{side}", ankle + (0, -.07, -.045), (.095, .17, .065), steel)
    hand = rest["hand_r"]; mace_head = rest["mace_head"]
    along("Mace shaft", armature, "mace", rest, .026, brown, shorten=1)
    ellipsoid("Mace pommel", armature, "mace", hand, (.045, .045, .045), brass)
    ellipsoid("Flanged mace", armature, "mace", mace_head, (.11, .11, .12), silver)
    direction = Vector(mace_head - hand).normalized()
    for dx, dy in ((.075, 0), (-.075, 0), (0, .075), (0, -.075)):
        ellipsoid("Flange", armature, "mace", mace_head + (dx, dy, 0), (.045, .045, .14), silver,
                  rotation=direction.to_track_quat("Z", "Y"))
    center = rest["hand_l"] + (0, -.075, -.06)
    shield_mesh(armature, center, steel)
    shield_mesh(armature, center, red, inset=.88, y_offset=-.04)
    ellipsoid("Shield boss", armature, "shield", center + (0, -.13, -.02), (.07, .035, .07), silver)
    scene.render.fps = 30
    return scene, armature


def set_pose(armature, joints, frame, bones=None):
    bpy.context.scene.frame_set(frame)
    max_error = 0.0
    for name, (a, b) in (bones or rig.BONES).items():
        bone = armature.pose.bones[name]
        bone.rotation_mode = "QUATERNION"
        bone.matrix = bone_matrix(joints, a, b)
        bpy.context.view_layer.update()
        max_error = max(max_error, (bone.head - Vector(joints[a])).length,
                        (bone.tail - Vector(joints[b])).length)
        for channel in ("location", "rotation_quaternion", "scale"):
            bone.keyframe_insert(data_path=channel, frame=frame)
    if max_error > 1e-5:
        raise ValueError(f"Blender armature differs from metric joint contract by {max_error}m")
    return max_error


def raster_meshes(scene, size):
    """Z-buffer actual evaluated Blender triangles, retaining depth and part IDs.

    Part IDs come from mesh ownership, never from guessing nearest 2D bones.
    All depths use the fixed camera's clip range, including across state sheets.
    """
    width, height = size
    depth = np.full((height, width), np.inf)
    ids = np.zeros((height, width), dtype=np.uint8)
    normals = np.zeros((height, width, 3), dtype=np.float32)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    basis = np.stack(rig.camera_basis())
    bounds = {}
    for obj in scene.objects:
        if obj.type != "MESH" or "part_id" not in obj:
            continue
        evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh(); mesh.calc_loop_triangles()
        world = np.array([tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices])
        xy, z = rig.project(world, size=size)
        part = PART_NAMES[int(obj["part_id"]) - 1]
        lo, hi = xy.min(axis=0), xy.max(axis=0)
        if part in bounds:
            lo = np.minimum(lo, bounds[part][0]); hi = np.maximum(hi, bounds[part][1])
        bounds[part] = [lo, hi]
        for triangle in mesh.loop_triangles:
            indices = list(triangle.vertices)
            p = xy[indices]; tz = z[indices]
            left, top = np.maximum(np.floor(p.min(axis=0)).astype(int), 0)
            right, bottom = np.minimum(np.ceil(p.max(axis=0)).astype(int), (width - 1, height - 1))
            if left > right or top > bottom:
                continue
            x, y = np.meshgrid(np.arange(left, right + 1) + .5, np.arange(top, bottom + 1) + .5)
            determinant = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
            if abs(determinant) < 1e-9:
                continue
            u = ((p[1, 1] - p[2, 1]) * (x - p[2, 0]) + (p[2, 0] - p[1, 0]) * (y - p[2, 1])) / determinant
            v = ((p[2, 1] - p[0, 1]) * (x - p[2, 0]) + (p[0, 0] - p[2, 0]) * (y - p[2, 1])) / determinant
            w = 1 - u - v
            local_z = u * tz[0] + v * tz[1] + w * tz[2]
            region = np.s_[top:bottom + 1, left:right + 1]
            update = (u >= -1e-7) & (v >= -1e-7) & (w >= -1e-7) & (local_z < depth[region])
            depth[region][update] = local_z[update]
            ids[region][update] = int(obj["part_id"])
            normal = rig.unit(np.cross(world[indices[1]] - world[indices[0]], world[indices[2]] - world[indices[0]]))
            normals[region][update] = basis @ normal
        evaluated.to_mesh_clear()
    return ids, depth, normals, {p: [[float(v) for v in xy] for xy in pair] for p, pair in bounds.items()}


def mesh_edge_lengths(scene):
    """Measure the evaluated geometry, catching skinning scale or rest-pose errors."""
    result = {}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in scene.objects:
        if obj.type != "MESH" or "part_id" not in obj:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        vertices = np.array([tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices])
        edges = np.array([tuple(edge.vertices) for edge in mesh.edges])
        result[obj.name] = np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)
        evaluated.to_mesh_clear()
    return result


def save_png(path, array):
    """Use Blender's PNG writer, so guide rendering needs no pip inside Blender."""
    array = np.asarray(array)
    h, w = array.shape[:2]
    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    if array.shape[2] == 3:
        array = np.concatenate((array, np.full((h, w, 1), 255, dtype=array.dtype)), axis=2)
    data = bpy.data.images.new("Pixelwright data export", width=w, height=h, alpha=True)
    data.colorspace_settings.name = "Non-Color"
    data.pixels.foreach_set(np.flipud(array.astype(np.float32) / 255).ravel())
    data.filepath_raw = str(path); data.file_format = "PNG"; data.save()
    bpy.data.images.remove(data)


def main():
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--no-render", action="store_true", help="Save and verify the rig without rendering previews")
    parser.add_argument("--skeleton-contract", type=Path,
                        help="Export a design-first contract as a bare armature with zero appearance meshes")
    args = parser.parse_args(arguments)
    root = args.out_dir.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use an empty output directory; existing guides must not be overwritten")
    root.mkdir(parents=True, exist_ok=True)
    contract = json.loads(args.skeleton_contract.read_text()) if args.skeleton_contract else rig.contract()
    check = rig.validate_contract(contract)
    if check["status"] != "pass":
        raise ValueError(check)
    scene, armature = create_scene(contract, skeleton_only=bool(args.skeleton_contract))
    timeline, projection_error, armature_error = 1, 0.0, 0.0
    rest_edges = mesh_edge_lengths(scene)
    mesh_edge_error = 0.0
    mesh_dimensions = {obj.name: {"bone": obj["bone"], "part_id": int(obj["part_id"]),
                                  "vertices": len(obj.data.vertices), "dimensions_m": list(obj.dimensions)}
                       for obj in scene.objects if obj.type == "MESH"}
    for state, animation in contract["animations"].items():
        directory = root / "frames" / state; directory.mkdir(parents=True)
        scene.timeline_markers.new(state, frame=timeline)
        for frame in animation["frames"]:
            joints = {name: np.array(value) for name, value in frame["joints_world"].items()}
            armature_error = max(armature_error, set_pose(armature, joints, timeline, contract["bones"]))
            for name, edges in mesh_edge_lengths(scene).items():
                mesh_edge_error = max(mesh_edge_error, float(np.max(np.abs(edges - rest_edges[name]))))
            if mesh_edge_error > 1e-5:
                raise ValueError(f"Skinned mesh dimensions changed: {mesh_edge_error}m")
            frame["blender_frame"] = timeline
            for name, xyz in joints.items():
                projected = world_to_camera_view(scene, scene.camera, Vector(xyz))
                expected = frame["joints_image"][name]
                actual = np.array((projected.x * contract["frame_size"][0], (1 - projected.y) * contract["frame_size"][1]))
                projection_error = max(projection_error, float(np.linalg.norm(actual - expected)))
            stem = f"frame_{frame['index']:02d}"
            if not args.no_render and not args.skeleton_contract:
                scene.render.filepath = str(directory / (stem + ".png"))
                bpy.ops.render.render(write_still=True)
                size = (scene.render.resolution_x, scene.render.resolution_y)
                ids, depth, normals, bounds = raster_meshes(scene, size)
                color = np.asarray(PART_COLORS, dtype=np.uint8)[ids]
                save_png(directory / (stem + ".parts.png"), color)
                near, far = rig.CAMERA["clip_start"], rig.CAMERA["clip_end"]
                depth_image = np.where(ids > 0, 255 - np.clip((depth - near) / (far - near) * 255, 0, 255), 0).astype(np.uint8)
                save_png(directory / (stem + ".depth.png"), depth_image)
                normal_image = np.where((ids > 0)[:, :, None], (normals * .5 + .5) * 255, 0).astype(np.uint8)
                save_png(directory / (stem + ".normal.png"), normal_image)
                frame["part_bounds_image"] = {p: [[x / rig.GUIDE_SCALE for x in xy] for xy in pair] for p, pair in bounds.items()}
                frame["guide"] = f"frames/{state}/{stem}.png"
                frame["parts"] = f"frames/{state}/{stem}.parts.png"
                frame["depth"] = f"frames/{state}/{stem}.depth.png"
                frame["normal"] = f"frames/{state}/{stem}.normal.png"
            timeline += max(1, round(frame["duration_ms"] * scene.render.fps / 1000))
    if projection_error > 1e-3:
        raise ValueError(f"Blender and independent orthographic projection disagree: {projection_error} cells")
    scene.frame_end = timeline; scene.frame_set(1)
    scene["pixelwright_camera_locked"] = True
    scene["pixelwright_units"] = "metres"
    bpy.ops.wm.save_as_mainfile(filepath=str(root / "knight-rig.blend"))
    if not args.skeleton_contract:
        contract["part_colors"] = {name: list(PART_COLORS[i + 1]) for i, name in enumerate(PART_NAMES)}
        contract["mesh_contract"] = mesh_dimensions
    (root / "rig.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8", newline="\n")
    check.update({"blender_version": bpy.app.version_string, "max_blender_projection_error_cells": projection_error,
                  "max_armature_joint_error_m": armature_error, "max_mesh_edge_error_m": mesh_edge_error,
                  "mesh_object_count": len(mesh_dimensions)})
    (root / "rig-check.json").write_text(json.dumps(check, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("PIXELWRIGHT_3D " + json.dumps(check), flush=True)


if __name__ == "__main__":
    main()
