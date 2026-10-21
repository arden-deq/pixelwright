"""Reproduce manual observations of candidate 3 only; never derive from guide targets.

Polygons and feature points below were annotated from the exported coordinate
previews. Rasterization intersects the actual alpha. A <=1.5-cell snap only
resolves boundary clicks. This is assisted manual annotation, not AI segmentation.
"""
from pathlib import Path
import hashlib,json,sys,math
import numpy as np
from PIL import Image,ImageDraw
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'pixelwright/scripts'))
import pixel_sequence as seq
RAW_SHA='dc0fe8307bfc78651c3903cca656b4156553eae7b4f8e69b1f021dfc6b57888c'
run=HERE/'run-v3'
assert hashlib.sha256((run/'raw/walk.png').read_bytes()).hexdigest()==RAW_SHA,'Changed art requires new independent observations.'
# Equipment polygons follow the visible material boundaries; the remainder is
# explicitly the flexible character/shaft part, not an inferred anatomy mask.
entries=[
 {'label':'reference','helmet':[[62,30],[67,30],[71,33],[71,44],[68,46],[61,45],[60,42],[60,34]],'shield':[[77,55],[87,53],[93,57],[94,70],[89,84],[84,83],[78,77],[76,61]],'mace_head':[[35,85],[41,83],[45,86],[44,92],[38,95],[34,91]],'features':{'pelvis':[64,65],'chest':[63,55],'head':[65,38],'near_ball':[49,107],'far_ball':[82,110],'near_heel':[59,107],'far_heel':[85,109],'shield_top':[84,54],'mace_center':[39,88],'mace_grip':[50,72]},'near_shin':[[58,87],[56,102]],'far_shin':[[76,89],[80,104]]},
 {'label':'0','helmet':[[56,25],[63,25],[67,28],[67,40],[62,45],[55,46],[54,40],[54,29]],'shield':[[75,50],[85,47],[92,51],[95,65],[91,84],[86,83],[79,76],[74,56]],'mace_head':[[27,81],[34,79],[38,84],[37,90],[31,93],[25,89]],'features':{'pelvis':[63,64],'chest':[58,53],'head':[60,35],'near_ball':[46,112],'far_ball':[75,109],'near_heel':[57,112],'far_heel':[81,107],'shield_top':[84,48],'mace_center':[31,86],'mace_grip':[47,71]},'near_shin':[[56,87],[53,105]],'far_shin':None},
 {'label':'1','helmet':[[60,25],[67,25],[71,29],[71,40],[66,44],[60,46],[58,40],[58,29]],'shield':[[80,50],[91,48],[98,52],[102,68],[97,84],[91,84],[84,77],[79,56]],'mace_head':[[27,83],[34,81],[38,85],[37,91],[31,95],[25,91]],'features':{'pelvis':[67,65],'chest':[64,54],'head':[65,35],'near_ball':[59,112],'far_ball':[83,109],'near_heel':[68,112],'far_heel':[89,100],'shield_top':[89,49],'mace_center':[31,88],'mace_grip':[50,72]},'near_shin':[[66,88],[66,105]],'far_shin':None},
 {'label':'2','helmet':[[58,25],[65,25],[69,29],[69,40],[64,44],[58,45],[56,40],[56,29]],'shield':[[77,49],[87,47],[95,52],[98,66],[93,83],[88,82],[80,75],[76,55]],'mace_head':[[26,81],[33,79],[37,84],[36,90],[30,94],[24,89]],'features':{'pelvis':[64,65],'chest':[61,54],'head':[63,35],'near_ball':[49,112],'far_ball':[78,104],'near_heel':[60,112],'far_heel':[82,95],'shield_top':[86,48],'mace_center':[30,86],'mace_grip':[47,71]},'near_shin':[[58,88],[57,105]],'far_shin':None},
 {'label':'3','helmet':[[61,25],[68,25],[72,29],[72,40],[67,44],[60,46],[59,40],[59,29]],'shield':[[82,50],[92,48],[99,53],[103,68],[97,84],[93,84],[85,77],[80,56]],'mace_head':[[28,81],[35,80],[39,85],[38,91],[32,94],[26,90]],'features':{'pelvis':[67,65],'chest':[65,54],'head':[66,35],'near_ball':[57,112],'far_ball':[77,109],'near_heel':[68,112],'far_heel':[82,105],'shield_top':[90,49],'mace_center':[32,87],'mace_grip':[51,71]},'near_shin':[[65,88],[65,105]],'far_shin':None},
 {'label':'4','helmet':[[57,25],[64,25],[68,29],[68,40],[63,44],[57,46],[55,40],[55,29]],'shield':[[78,50],[88,48],[96,53],[99,68],[94,84],[90,83],[82,76],[77,56]],'mace_head':[[24,81],[31,79],[35,84],[34,90],[28,94],[22,89]],'features':{'pelvis':[63,65],'chest':[59,54],'head':[61,35],'near_ball':[41,108],'far_ball':[76,111],'near_heel':[49,110],'far_heel':[84,108],'shield_top':[86,49],'mace_center':[28,86],'mace_grip':[46,71]},'near_shin':[[53,88],[48,103]],'far_shin':None},
 {'label':'5','helmet':[[58,25],[65,25],[69,29],[69,40],[64,44],[58,45],[56,40],[56,29]],'shield':[[78,49],[88,47],[96,52],[100,68],[95,84],[90,83],[82,76],[77,55]],'mace_head':[[27,81],[34,79],[38,84],[37,90],[31,94],[25,89]],'features':{'pelvis':[64,65],'chest':[61,54],'head':[63,35],'near_ball':[53,111],'far_ball':[84,106],'near_heel':[64,111],'far_heel':[88,96],'shield_top':[87,48],'mace_center':[31,86],'mace_grip':[48,71]},'near_shin':[[63,89],[61,104]],'far_shin':None},
 {'label':'6','helmet':[[58,24],[65,24],[69,28],[69,39],[64,43],[58,44],[56,39],[56,28]],'shield':[[77,49],[87,47],[95,52],[99,67],[94,83],[89,82],[81,75],[76,55]],'mace_head':[[24,79],[32,78],[36,82],[35,89],[29,93],[22,88]],'features':{'pelvis':[64,64],'chest':[60,53],'head':[63,34],'near_ball':[59,108],'far_ball':[73,109],'near_heel':[67,103],'far_heel':[82,109],'shield_top':[86,48],'mace_center':[29,85],'mace_grip':[47,69]},'near_shin':[[59,88],[65,102]],'far_shin':None},
 {'label':'7','helmet':[[58,25],[65,25],[69,29],[69,40],[64,44],[58,45],[56,40],[56,29]],'shield':[[78,50],[88,48],[96,53],[100,68],[95,84],[90,83],[82,76],[77,56]],'mace_head':[[26,81],[33,79],[37,84],[36,90],[30,94],[24,89]],'features':{'pelvis':[64,65],'chest':[61,54],'head':[63,35],'near_ball':[48,111],'far_ball':[74,111],'near_heel':[59,111],'far_heel':[80,110],'shield_top':[87,49],'mace_center':[30,86],'mace_grip':[48,71]},'near_shin':[[57,88],[53,104]],'far_shin':None}
]

def runs(mask):
 result=[]
 for y,row in enumerate(mask):
  edges=np.flatnonzero(np.diff(np.r_[False,row,False].astype(np.int8)))
  result.extend([[y,int(a),int(b)] for a,b in zip(edges[::2],edges[1::2])])
 return result

snaps=[]
def snap(p,mask,label):
 if p is None:return None
 x,y=p
 if mask[y,x]:return p
 yy,xx=np.nonzero(mask);dist=(xx-x)**2+(yy-y)**2;j=int(dist.argmin())
 if dist[j]>1.5**2:raise ValueError(f'{label}: point {p} needs >1.5-cell adjustment; re-inspect actual pixels (nearest {int(xx[j]),int(yy[j])}).')
 q=[int(xx[j]),int(yy[j])];snaps.append({'label':label,'click':p,'observed_visible_cell':q,'distance':math.sqrt(float(dist[j]))});return q

def extent(mask,axis):
 yy,xx=np.nonzero(mask);coord=xx if axis==0 else yy
 out=[]
 for v in [coord.min(),coord.max()]:
  idx=np.where(coord==v)[0];j=idx[len(idx)//2];out.append([int(xx[j]),int(yy[j])])
 return out

def observe(entry,image):
 pix=np.array(image.convert('RGBA'));visible=pix[:,:,3]>0;masks={}
 for key in ['helmet','shield','mace_head']:
  canvas=Image.new('1',image.size);ImageDraw.Draw(canvas).polygon([tuple(p) for p in entry[key]],fill=1)
  masks[key]=np.array(canvas,dtype=bool)&visible
 masks['character']=visible&~(masks['helmet']|masks['shield']|masks['mace_head'])
 measures={'helmet':{'height':extent(masks['helmet'],1),'width':extent(masks['helmet'],0)},'shield':{'height':extent(masks['shield'],1)},'mace_head':{'span':extent(masks['mace_head'],0)},'character':{}}
 for name in ['near_shin','far_shin']:
  pair=entry[name]
  if pair is not None:measures['character'][name]=[snap(p,masks['character'],f'{entry["label"]}.{name}') for p in pair]
 return {'parts':{k:{'visibility':'visible','mask':runs(v),'measurements':measures[k]} for k,v in masks.items()},'landmarks':{k:snap(p,masks[{'head':'helmet','shield_top':'shield','mace_center':'mace_head'}.get(k,'character')],f'{entry["label"]}.{k}') for k,p in entry['features'].items()}}

obs=seq.observation_template(run)
obs['method']='Codex manual annotation from candidate-3-unobserved reference/000..007.coordinates.png, independent of the intended pose diagram. Near=bright greave/boot on screen-left in contacts; far=shadowed rear leg. Semantic material polygons intersect actual alpha; remaining visible pixels belong to character/shaft. Approximate boundary/point uncertainty ±1 native cell; recorded nearest-visible snaps <=1.5 cells. Equipment lengths are visible silhouette extents between actual boundary cells; not 3D intrinsic dimensions. Far shin endpoints in animation are obscured/ambiguous and remain unmeasured. No intended guide coordinates are read or copied.'
obs['reference']=observe(entries[0],Image.open(run/'reference-native.png'))
frames=[]
for i,entry in enumerate(entries[1:]):frames.append(observe(entry,Image.open(HERE/f'candidate-3-unobserved/walk/frames/{i:03d}.native.png')))
obs['states']['walk']['frames']=frames
obs['states']['walk']['review']={'status':'changes_needed','reviewer':'Codex assistant visual review; no human approval','observations':[
 'The third generation corrected the exaggerated overall sprite scale: shared frame area/palette checks pass. Each pose is freshly generated from the selected knight plus an authored 2D placement diagram; no 3D render or pasted-part animation was used.',
 'The bright near greave still stays forward in both nominal contact poses 0 and 4. The far leg lifts but does not make the required opposite forward landing; this is not a completed alternating walk.',
 'Near boot screen positions change irregularly rather than moving four cells right during the intended plant. Far contact frames also show drift and an airborne boot. Quantify these actual observations using the frozen root restoration, not fitted root offsets.',
 'The belt changes little vertically and does not clearly descend on both loading poses. Arm/shield motion and cloth are visible but do not establish believable support or physical center of mass.',
 'The last-to-first feature displacement is checked, but that alone cannot validate a cycle whose stance exchange is absent. Helmet and shield have enlarged visible silhouettes versus the selected design. Pixel-grid PASS applies to the projected derivative only.',
 'The legs overlap and change foreshortening, so the far shin cannot be measured reliably. Leave it unverified instead of inventing hidden anatomy.'
]}
(HERE/'observed.json').write_text(json.dumps(obs,ensure_ascii=False,indent=2)+'\n')
(HERE/'observation-method.json').write_text(json.dumps({'source_sha256':RAW_SHA,'independence':'All clicked points/polygons come from actual exported coordinate previews, not pose constraints.','uncertainty_native_cells':1,'snap_limit_native_cells':1.5,'snaps':snaps,'manual_entries':entries},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'observed','frames':len(frames),'snaps':snaps},ensure_ascii=False,indent=2))
