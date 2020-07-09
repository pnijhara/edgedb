#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2020-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either nodeess or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


"""EdgeQL nodeession normalization functions."""


from __future__ import annotations
from typing import *

import copy
import functools

from edb.common.ast import base
from edb.edgeql import ast as qlast
from edb.schema import expraliases as s_aliases
from edb.schema import schema as s_schema
from edb.schema import types as s_types
from edb.schema import name as sn


@functools.singledispatch
def normalize(
    node: Any, *,
    schema: s_schema.Schema,
    modaliases: Mapping[Optional[str], str],
) -> Any:
    raise ValueError(f'normalize: cannot handle {node!r}')


@normalize.register
def normalize_Base(
    node: qlast.Base,
    *,
    schema: s_schema.Schema,
    modaliases: Mapping[Optional[str], str],
) -> qlast.Base:
    node = copy.copy(node)

    for field, value in base.iter_fields(node):
        if isinstance(value, qlast.Base):
            setattr(node, field,
                    normalize(value, schema=schema, modaliases=modaliases))
        elif isinstance(value, list):
            if value and isinstance(value[0], qlast.Base):
                setattr(node, field,
                        [normalize(el, schema=schema, modaliases=modaliases)
                         for el in value])

    return node


@normalize.register
def normalize_DDL(
    node: qlast.DDL,
    *,
    schema: s_schema.Schema,
    modaliases: Mapping[Optional[str], str],
) -> qlast.DDL:
    raise ValueError(f'normalize: cannot handle {node!r}')


@normalize.register
def compile_Path(
    node: qlast.Path,
    *,
    schema: s_schema.Schema,
    modaliases: Mapping[Optional[str], str],
) -> qlast.Path:

    node = copy.copy(node)

    # We only need to resolve non-partial paths
    if not node.partial:
        steps = []
        for step in node.steps:
            if isinstance(step, (qlast.Expr, qlast.TypeIntersection)):
                steps.append(
                    normalize(step, schema=schema, modaliases=modaliases))
            elif isinstance(step, qlast.ObjectRef):
                # This is a specific path root, resolve it.
                if not step.module:
                    obj = schema.get(
                        step.name,
                        default=None,
                        # We only care to resolve an Alias or a Type
                        # as the root of the path.
                        condition=lambda o: (
                            isinstance(o, (s_aliases.Alias, s_types.Type))
                        ),
                        module_aliases=modaliases,
                    )
                    if obj is not None:
                        step.module = obj.get_name(schema).module
                    steps.append(step)
            else:
                steps.append(step)

        node.steps = steps

    return node


@normalize.register
def compile_FunctionCall(
    node: qlast.FunctionCall,
    *,
    schema: s_schema.Schema,
    modaliases: Mapping[Optional[str], str],
) -> qlast.FunctionCall:

    node = copy.copy(node)

    if isinstance(node.func, str):
        funcs = schema.get_functions(
            node.func, default=tuple(), module_aliases=modaliases)
        if funcs:
            # As long as we found some functions, they will be from
            # the same module (the first valid resolved module for the
            # function name will mask "std").
            _, fname = funcs[0].get_name(schema).as_tuple()
            _, module, name = sn.split_name(sn.shortname_from_fullname(fname))
            node.func = (module, name)

    node.args = [normalize(arg, schema=schema, modaliases=modaliases)
                 for arg in node.args]
    node.kwargs = {key: normalize(val, schema=schema, modaliases=modaliases)
                   for key, val in node.kwargs}

    return node


@normalize.register
def compile_TypeName(
    node: qlast.TypeName,
    *,
    schema: s_schema.Schema,
    modaliases: Mapping[Optional[str], str],
) -> qlast.TypeName:

    node = copy.copy(node)

    # Resolve the main type
    if isinstance(node.maintype, qlast.ObjectRef):
        # This is a specific path root, resolve it.
        if not node.maintype.module:
            maintype = schema.get(
                node.maintype.name,
                default=None,
                type=s_types.Type,
                module_aliases=modaliases,
            )
            if maintype is not None:
                node.maintype.module = maintype.get_name(schema).module

    if node.subtypes is not None:
        node.subtypes = [normalize(st, schema=schema, modaliases=modaliases)
                         for st in node.subtypes]

    return node
