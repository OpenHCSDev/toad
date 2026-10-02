"""Serialize the existing reviewed runtime member from a parent-supplied plan."""
from pathlib import Path
import argparse,json,sys
out=Path(__file__).parent
sys.path.insert(0,str(out/'operator-freeze'))
from agent_comms.field_codec import FieldCodec
from native_schema_carry import NativeSchemaCarryPlan,NativeSchemaDeclaration
from runtime_installation import CarryNativeRuntimeInstallation
from routing_recovery import write_original
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--carry-plan',type=Path,required=True)
parser.add_argument('--runtime-installation',type=Path,required=True)
args=parser.parse_args()
original=FieldCodec.decode(NativeSchemaDeclaration,json.loads((out/'original-declaration.json').read_text()))
plan=FieldCodec.decode(NativeSchemaCarryPlan,json.loads(args.carry_plan.read_text()))
assert plan.original==original
assert plan.target==NativeSchemaDeclaration.observe()
plan.require_candidate()
member=CarryNativeRuntimeInstallation(goal_schema=original.goal,plan=plan)
write_original(args.runtime_installation,(json.dumps(FieldCodec.encode(member),indent=2)+'\n').encode())
print(json.dumps({'state':'Reviewed existing CarryNativeRuntimeInstallation serialized; not installed/published','runtime_installation':str(args.runtime_installation)}))
