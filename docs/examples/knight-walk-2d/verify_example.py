"""Verify saved artifact bytes/timing and summarize failures without accepting art."""
from pathlib import Path
import hashlib,json,math
from datetime import datetime,timezone
import numpy as np
from PIL import Image,ImageSequence
HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

report=read(HERE/'audit/report.json');spec=read(HERE/'run-v3/contract.json')['spec'];obs=read(HERE/'observed.json')
state=report['states']['walk'];source=HERE/'run-v3/raw/walk.png'
assert state['source_sha256']==sha(source)==obs['states']['walk']['source_sha256']
assert report['contract_sha256']==sha(HERE/'run-v3/contract.json')
assert report['observations_sha256']==sha(HERE/'observed.json')
raw=Image.open(source);native=Image.open(HERE/'audit/walk/native.png').convert('RGBA');rendered=Image.open(HERE/'audit/walk/rendered.png').convert('RGBA')
assert raw.width*256==raw.height*512
assert native.size==(512,256) and rendered.size==(2048,1024)
assert rendered.tobytes()==native.resize(rendered.size,Image.Resampling.NEAREST).tobytes()
pixels=np.array(native);colors=np.unique(pixels[pixels[:,:,3]>0],axis=0)
assert len(colors)<=24 and set(np.unique(pixels[:,:,3]))=={0,255}
assert np.all(pixels[pixels[:,:,3]==0]==0)
# The built-in GIF is explicitly a flat-background preview; the PNG keeps alpha.
gif_path=HERE/'audit/walk/pixel-audit/animations/walk.gif';gif=Image.open(gif_path)
assert gif.n_frames==8 and gif.size==(512,512) and gif.info['loop']==0
actual_durations=[];gif_matches=[];frame_hashes=[]
for i,frame in enumerate(ImageSequence.Iterator(gif)):
 art=Image.open(HERE/f'audit/walk/frames/{i:03d}.native.png').convert('RGBA').resize(gif.size,Image.Resampling.NEAREST)
 expected=Image.alpha_composite(Image.new('RGBA',gif.size,(48,52,62,255)),art).convert('RGB')
 match=frame.convert('RGB').tobytes()==expected.tobytes();assert match
 gif_matches.append(match);actual_durations.append(frame.info['duration'])
 frame_hashes.append(sha(HERE/f'audit/walk/frames/{i:03d}.native.png'))
assert actual_durations==spec['states']['walk']['durations_ms']==[110]*8
assert len(set(frame_hashes))==8
# Prove tolerances were not relaxed between the three pre-generation contracts.
specs=[read(HERE/p) for p in ['spec.json','spec-v2.json','spec-v3.json']]
threshold_fields=['area_tolerance','min_shape_match','min_color_overlap','min_design_match','measurements']
for earlier in specs[:2]:
 assert earlier['limits']==specs[2]['limits']
 for part in specs[2]['parts']:
  assert {k:earlier['parts'][part][k] for k in threshold_fields}=={k:specs[2]['parts'][part][k] for k in threshold_fields}
 assert earlier['states']['walk']['motion']==specs[2]['states']['walk']['motion']
 assert earlier['states']['walk']['contacts']==specs[2]['states']['walk']['contacts']
 assert earlier['states']['walk']['durations_ms']==specs[2]['states']['walk']['durations_ms']
assert report['status']=='fail' and state['pixel_status']=='pass'
assert report['human_approval_recorded'] is False
assert state['art_review']['status']=='changes_needed'
frames=obs['states']['walk']['frames'];pelvis=[f['landmarks']['pelvis'] for f in frames]
loop=[]
for name,metrics in state['motion']['landmarks'].items():
 transition=metrics['transitions'][-1];assert transition['from']==7 and transition['to']==0
 rule=spec['states']['walk']['motion'][name]
 assert transition['speed']<=rule['max_speed']
 loop.append({'feature':name,'speed_cells_per_second':transition['speed'],'limit':rule['max_speed']})
contacts=[]
for measured,rule in zip(state['motion']['contacts'],spec['states']['walk']['contacts']):
 assert measured['landmark']==rule['landmark'] and measured['drift']>rule['max_drift']
 contacts.append({**measured,'limit':rule['max_drift'],'status':'fail'})
helmet_heights=[f['parts']['helmet']['measurements']['height'] for f in state['frames']]
result={
 'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
 'artifact_integrity_status':'pass','art_quality_status':'fail','human_approved':False,
 'source':{'size':list(raw.size),'sha256':sha(source),'raw_grid_certified':False},
 'derivative':{'frame_size':[128,128],'sheet_native':[512,256],'sheet_rendered':[2048,1024],'cell_scale':4,'visible_colors':len(colors),'binary_alpha':True,'canonical_transparent_rgba':True,'whole_canvas_nearest_projection':True,'per_frame_fitting':False,'pixel_status':state['pixel_status']},
 'gif':{'path':'audit/walk/pixel-audit/animations/walk.gif','size':list(gif.size),'frames':8,'durations_ms':actual_durations,'total_ms':sum(actual_durations),'loop':True,'all_frames_exactly_match_flat_background_preview':all(gif_matches),'background_rgb':[48,52,62],'sha256':sha(gif_path),'native_frame_sha256':frame_hashes},
 'contact':contacts,
 'pelvis':{'actual_xy':pelvis,'observed_vertical_range_cells':max(p[1] for p in pelvis)-min(p[1] for p in pelvis),'target_vertical_range_cells':[2,4],'first_loading_delta_y':pelvis[1][1]-pelvis[0][1],'second_loading_delta_y':pelvis[5][1]-pelvis[4][1],'weight_transfer_status':'changes_needed','physical_center_of_mass_measured':False},
 'loop_boundary':{'timed_feature_speed_status':'pass','all_adjacent_and_wrap_speed_acceleration_violations':sum(i['code'] in ['MOTION_SPEED_EXCEEDED','MOTION_ACCELERATION_EXCEEDED'] for i in report['issues']),'features':loop,'natural_cycle_accepted':False,'reason':'Numeric continuity does not prove alternating support, physical contact or consistent identity.'},
 'helmet_visible_height_range_cells':[min(helmet_heights),max(helmet_heights)],
 'observation_uncertainty_native_cells':1,'same_acceptance_thresholds_across_candidates':True,
 'issue_counts':report['issue_counts'],
 'scope':'Verifies saved PNG/GIF and reproduces known failing artwork findings. Does not certify the generated walk as improved/natural.'
}
write(HERE/'verification.json',result)
# Exact tool call inputs, ordered roles, frozen prompt and untouched raw hashes.
source_outputs=[
 ('run','candidate-1-unobserved',[(HERE/'run/reference-native.png','selected identity')],'/Users/namjungduck/.codex/generated_images/01a15cf8-8d52-71b3-8a8d-2cc435109d80/exec-23987f2b-bbf3-4077-8087-c3880d8626f9.png'),
 ('run-v2','candidate-2-unobserved',[(HERE/'run-v2/reference-source.png','selected identity'),(HERE/'pose-constraints.png','authored 2D motion layout only')],'/Users/namjungduck/.codex/generated_images/01a15cf8-8d52-71b3-8a8d-2cc435109d80/exec-73b8aa5e-fd24-42bb-b4d4-ed68b8c443d3.png'),
 ('run-v3','audit',[(HERE/'pose-constraints-v3.png','authored 2D motion layout only'),(HERE/'run-v3/reference-source.png','selected identity')],'/Users/namjungduck/.codex/generated_images/01a15cf8-8d52-71b3-8a8d-2cc435109d80/exec-1614592f-24dc-4ca7-ad31-25dd72d9d014.png')]
candidates=[]
for run_name,audit_name,inputs,original_path in source_outputs:
 directory=HERE/run_name;prompt=directory/'prompts/walk.txt';art=directory/'raw/walk.png'
 actual=Path(original_path)
 if actual.exists():assert actual.read_bytes()==art.read_bytes()
 candidates.append({'run':run_name,'contract_sha256':sha(directory/'contract.json'),'prompt':str(prompt.relative_to(HERE)),'prompt_sha256':sha(prompt),'prompt_sent_verbatim':True,'inputs':[{'path':str(p.relative_to(HERE)),'role':role,'sha256':sha(p)} for p,role in inputs],'raw':str(art.relative_to(HERE)),'raw_sha256':sha(art),'audit':audit_name+'/report.json','chosen':run_name=='run-v3'})
write(HERE/'generation.json',{'tool':'Codex built-in image_gen','mode':'built-in; no CLI/HTTP adapter used','model':None,'model_disclosure':'Host did not expose a model identifier.','transparent_background_requested':True,'calls':3,'skeleton_3d_inputs':0,'artwork_method':'Fresh generated 2D knight artwork; optional authored 2D stick-motion constraints, not rendered armor, cutout tweening, or copied observations.','final_artwork_status':'changes_needed','human_approved':False,'candidates':candidates})
print(json.dumps({k:result[k] for k in ['artifact_integrity_status','art_quality_status','contact','pelvis','issue_counts']},ensure_ascii=False,indent=2))
