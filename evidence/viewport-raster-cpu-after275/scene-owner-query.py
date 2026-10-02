import ast,json
from collections import Counter
from pathlib import Path
from nominal_refactor_advisor.ast_tools import parse_python_module_roots,ClassFunctionStackNodeVisitor
from nominal_refactor_advisor.source_index import build_source_index
roots=(Path('/home/ts/wt/toad-viewport-raster-cpu-continuation-20261001/src/toad'),Path('/home/ts/wt/textual-intrinsic-placement-after18-20261001/src/textual'))
modules=parse_python_module_roots(roots,use_parse_cache=False,parse_workers=1)
index=build_source_index(modules,())
subjects={'restore_native','refresh_revealed','present_retained_native_session','prepare_retained_session','prepare_presentation','activate','select','_switch_mode_ready','_prepare_compositor_refresh','_compositor_refresh','_refresh_layout','_damage_geometry','reflow','reflow_visible','full_map','visible_widgets','render_update','update_widgets','transform_running_animation','transform_values','check_idle','_on_idle','_on_timer_update','_refresh_pending','frame_presentation'}
family={'TranscriptPresentation','NativeSessionSurface','WorkspaceSource','BoundWorkspaceSource','LoadingWorkspaceSource','ShownWorkspaceSource','WorkspaceSessions','FramePresentation','FrameState','PendingFrame','PresentedFrame','WritingFrame','SuspendedFrame','WorkspaceScreen','MeasuredWorkspaceLayout','WorkspaceLayoutSnapshot','ViewportPresentation','DocumentViewport','Screen','Compositor','SubtreeGeometry','PlacedSubtreeGeometry','IntrinsicSubtreeGeometry','SubtreeGeometryKey','SubtreeMapGeometry','Animator','Animation','SimpleAnimation','ScalarAnimation'}
references=[]
class References(ClassFunctionStackNodeVisitor):
 def visit_Attribute(self,node):
  if node.attr in subjects:
   references.append({'file':str(self.module.path),'owner':self.qualname,'line':node.lineno,'subject':node.attr,'receiver':ast.unparse(node.value),'access':type(node.ctx).__name__})
  self.generic_visit(node)
visitor=References()
for module in modules:
 visitor.module=module;visitor.visit(module.module)
declarations=[{'symbol':index.symbol_for_target(target),'file':target.file_path,'name':target.qualname,'line':target.line,'end_line':target.end_line,'bases':list(target.base_names)} for target in index.ast_targets if (target.is_class and target.name in family) or (target.is_function_like and target.name in subjects)]
result={'tool':'NRA ParsedModule + SourceIndex + original ClassFunctionStackNodeVisitor','roots':[str(p) for p in roots],'parsed_modules':len(modules),'declarations':declarations,'attribute_references':references,'limits':['This is complete lexical source coverage for two declared package roots, not proof of dynamic receiver resolution, behavioral equivalence or installed paint. Candidate receiver paths were checked against their actual nominal owners in OWNER.md. Tests/external compiled code are outside these product roots.']}
Path('/home/ts/wt/toad-viewport-raster-cpu-continuation-20261001/evidence/viewport-raster-cpu-after275/scene-owner-ast-query.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'parsed_modules':len(modules),'declarations':len(declarations),'lexical_references':len(references),'removed_method_declarations':sum(d['name'].endswith('present_retained_native_session') for d in declarations),'removed_method_references':sum(r['subject']=='present_retained_native_session' for r in references),'classes':dict(Counter(d['name'] for d in declarations if d['name'] in family))}))
