import os

import bpy
import bmesh

from mathutils import Vector, Matrix

from bpy_extras.io_utils import ExportHelper
from bpy.props import (PointerProperty,
                       CollectionProperty,
                       EnumProperty,
                       StringProperty,
                       FloatProperty,
                       IntProperty,
                       FloatVectorProperty)
from bpy.types import Operator, Panel, PropertyGroup

_HEADER_FILE_TEMPLATE = """
#ifndef _{defname}_H_
#define _{defname}_H_

{rocket_names}

static const DWORD ntdvtx{ccage_suffix} = {ccage_vert_count};
static TOUCHDOWNVTX tdvtx{ccage_suffix}[ntdvtx{ccage_suffix}] = {{
	{ccage_verts}
}};

const {rocket_pos_name} = {{
    {rocket_pos}
}};

const {rocket_dir_name} = {{
    {rocket_dir}
}};

{rocket_groups}

#endif // _{defname}_H_
""".strip() + '\n'


def convert_to_orbiter(pos):
    # Convert to orbiter coordinate system
    return -pos[0], pos[2], -pos[1]


class bmesh_object:
    def __init__(self, obj):
        self._mesh = obj.data
        self._bm = None

    def __enter__(self):
        self._bm = bmesh.new()
        self._bm.from_mesh(self._mesh)
        return self._bm

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._bm.to_mesh(self._mesh)
        self._bm.free()


class OrbiterExportHeaderFile(Operator):
    """Export the settings to the c++ header file"""
    bl_idname = "orbiter.export_header_file"
    bl_label = "Export Header"

    def execute(self, context):
        orbiter = context.scene.orbiter
        template_context = {
            'defname': os.path.splitext(os.path.basename(orbiter.header_file))[0].upper()
        }

        # First get the collision cage
        vert_list = []
        with bmesh_object(bpy.data.objects[orbiter.ccage]) as bm:
            for v in bm.verts:
                # Conversion to orbiter is: z=-y,y=z,x=-x ; tri[1]<-> tri[2] ; v=1-v

                # Convert to orbiter coordinate system
                x, y, z = convert_to_orbiter(v.co)

                # Clean up the numbers a little
                x = round(x, 2)
                y = round(y, 2)
                z = round(z, 2)

                s = '{{_V({x}, {y}, {z}), {props}}}'.format(x=x, y=y, z=z, props='1e6, 1e5, 1.6')
                vert_list.append(s)

        template_context['ccage_verts'] = ',\n    '.join(vert_list)
        template_context['ccage_vert_count'] = len(vert_list)
        template_context['ccage_suffix'] = orbiter.ccage_suffix

        # Now get the rockets
        all_rockets = set()
        for group in orbiter.rocket_groups:
            all_rockets.update(bpy.data.groups[group.group].objects)

        rockets = []
        rockets_pos = []
        rockets_dir = []
        for rocket in all_rockets:
            if rocket.type == 'EMPTY':
                name = rocket.name.upper()

                mat = rocket.matrix_world * Matrix.Translation((0, 0, 1))
                dir = Vector((mat[0][3], mat[1][3], mat[2][3])) - rocket.location

                # The empties point in the direction the rocket fires, in orbiter it's the opposite.
                dir.negate()

                # index of this rocket
                index = len(rockets_pos)
                str_pos = '{{{}, {}, {}}}'.format(*convert_to_orbiter(rocket.location))
                str_dir = '{{{}, {}, {}}}'.format(*convert_to_orbiter(dir))
                str_rocket = '#define {prefix}{name} {index};'.format(prefix="", name=name, index=index)

                rockets_pos.append(str_pos)
                rockets_dir.append(str_dir)

                rockets.append(str_rocket)

        rocket_groups = ''
        for group in orbiter.rocket_groups:
            group_rockets = []
            for rocket in bpy.data.groups[group.group].objects:
                group_rockets.append(rocket.name)

            rocket_groups += 'const int {group} {{\n    {rockets}\n}}\n'.format(
                group=group.name,
                rockets=',\n    '.join(group_rockets))

        template_context['rocket_names'] = '\n'.join(rockets)

        template_context['rocket_pos_name'] = 'ROCKET_POSITIONS'
        template_context['rocket_pos'] = ',\n    '.join(rockets_pos)

        template_context['rocket_dir_name'] = 'ROCKET_DIRECTIONS'
        template_context['rocket_dir'] = ',\n    '.join(rockets_dir)
        template_context['rocket_groups'] = rocket_groups

        print(template_context)

        with open(bpy.path.abspath(orbiter.header_file), 'w') as f:
            f.write(_HEADER_FILE_TEMPLATE.format(**template_context))

        return {'FINISHED'}


class OrbiterRocketGroupAdd(Operator):
    """Add a rocket group"""
    bl_idname = "orbiter.rocket_group_add"
    bl_label = "Add Rocket Group"

    def execute(self, context):
        orbiter = context.scene.orbiter
        rg = orbiter.rocket_groups.add()

        orbiter.rocket_groups_active_index = orbiter.rocket_groups.values().index(rg)

        return {'FINISHED'}


class OrbiterRocketGroupRemove(Operator):
    """Remove a rocket group"""
    bl_idname = "orbiter.rocket_group_remove"
    bl_label = "Remove Rocket Group"

    def execute(self, context):
        orbiter = context.scene.orbiter
        orbiter.rocket_groups.remove(orbiter.rocket_groups_active_index)

        orbiter.rocket_groups_active_index = max(orbiter.rocket_groups_active_index - 1, 0)

        return {'FINISHED'}


class OrbiterRocketGroupMove(Operator):
    """Move a rocket group"""
    bl_idname = "orbiter.rocket_group_move"
    bl_label = "Move Rocket Group"

    direction = EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        orbiter = context.scene.orbiter
        index = orbiter.rocket_groups_active_index
        target = index + (-1 if self.direction == 'UP' else 1)

        # Make sure the target is a valid index
        if target < 0 or target >= len(orbiter.rocket_groups):
            return {'FINISHED'}

        orbiter.rocket_groups.move(index, target)
        orbiter.rocket_groups_active_index = target

        return {'FINISHED'}


class OrbiterRocketGroup(PropertyGroup):
    group = StringProperty(name="Rocket Group",
                           description="Group to export as a rocket group")


class OrbiterProperties(PropertyGroup):
    rocket_groups = CollectionProperty(type=OrbiterRocketGroup)
    rocket_groups_active_index = IntProperty()

    ccage = StringProperty(
        name="Collision Cage",
        description="Object to use as collision cage"
    )

    ccage_suffix = StringProperty(
        name="Collision Cage Suffix",
        description="Suffix to use in the name of the collision cage"
    )

    header_file = StringProperty(
        name="Header File",
        description="Path to the header file where the data will be exported",
        subtype="FILE_PATH"
    )


class ORBITER_UL_rockets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "name", emboss=False, text="")
        layout.prop_search(item, "group", bpy.data, "groups", text="")


class OrbiterToolPanel(Panel):
    """Orbiter Export Tool Panel"""
    bl_label = "Orbiter Export"
    bl_idname = "VIEW3D_PT_orbiter_export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = "object"

    def draw(self, context):
        layout = self.layout
        orbiter = context.scene.orbiter

        layout.prop_search(orbiter, "ccage", bpy.data, "objects")
        rg = None
        rows = 1
        if len(orbiter.rocket_groups) > 0 and orbiter.rocket_groups_active_index < len(orbiter.rocket_groups):
            rg = orbiter.rocket_groups[orbiter.rocket_groups_active_index]
            rows = 3

        row = layout.row()
        row.template_list("ORBITER_UL_rockets", "", orbiter, "rocket_groups", orbiter, "rocket_groups_active_index",
                          rows=rows)

        col = row.column(align=True)
        col.operator("orbiter.rocket_group_add", icon='ZOOMIN', text="")
        col.operator("orbiter.rocket_group_remove", icon='ZOOMOUT', text="")

        if rg:
            col.separator()
            col.operator("orbiter.rocket_group_move", icon='TRIA_UP', text="").direction = 'UP'
            col.operator("orbiter.rocket_group_move", icon='TRIA_DOWN', text="").direction = 'DOWN'

        layout.prop(orbiter, "header_file")
        layout.prop(orbiter, "ccage_suffix")
        layout.operator("orbiter.export_header_file")


def register():
    bpy.utils.register_module(__name__)

    bpy.types.Scene.orbiter = PointerProperty(type=OrbiterProperties)


def unregister():
    bpy.utils.unregister_module(__name__)

    del bpy.types.Scene.orbiter


if __name__ == "__main__":
    register()
