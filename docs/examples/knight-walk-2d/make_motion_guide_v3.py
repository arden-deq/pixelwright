"""Author a leftward 2D constraint diagram; never edits/generated knight art."""
from pathlib import Path
import json, math
from PIL import Image,ImageDraw,ImageFont
HERE=Path(__file__).resolve().parent
spec=json.loads((HERE/'spec-v2.json').read_text())
spec['name']='Crimson knight grounded walk'
spec['description']='Use-case: stylized-concept. INPUT 1 is a simple pose-placement diagram ONLY. INPUT 2 is the selected 2D knight: sole authority for appearance, camera, armor, greathelm/plume, red-gold tabard and shield, flanged mace. Redraw fresh pixel art using input 2, following input 1 only for leg motion and canvas placement. Walk toward screen-LEFT, matching the knight facing. Keep equipment on the SAME sides; never mirror the character. Crucial: character is only 88 native cells tall, from y=24 to y=112 in a 128-cell slot, with LARGE empty margins. Do not fill the slot. Use crisp low-resolution pixel clusters, not smooth painting.'
shortparts={
 'helmet':'Rigid steel helmet excluding plume, same 11-cell width and 15-cell height; preserve visor and trim.',
 'shield':'Rigid red shield and gold emblem/rim; same 30-cell long axis. Subtle weighted shoulder follow-through.',
 'mace_head':'Small flanged mace head, same 10-cell width, always attached to its shaft. No weapon redesign.',
 'character':'Remaining pixels: plume, torso, arms, belt, tabard, legs, boots, mace shaft. Preserve armor proportions; articulate knees/ankles with weight and overlap.'}
for key,desc in shortparts.items():spec['parts'][key]['description']=desc
shortfeatures={'pelvis':'Central belt buckle; show load absorption and alternating support shift.','chest':'Center of chest heraldry.','head':'Center of steel helmet.','near_ball':'Underside of near boot ball, not heel.','far_ball':'Underside of far boot ball, not heel.','near_heel':'Bottom back corner of near boot.','far_heel':'Bottom back corner of far boot.','shield_top':'Center of shield top rim.','mace_center':'Center of flanged mace head.','mace_grip':'Visible gauntlet center gripping mace shaft.'}
for key,desc in shortfeatures.items():spec['landmarks'][key]['description']=desc
s=spec['states']['walk']
s['intent']='EXACTLY 8 genuinely sequential walk poses, 4 columns x 2 rows, row-major, transparent 2:1 PNG (2048x1024). Eight 128-square logical slots in a 512x256 logical sheet. In-place leftward armored walk, 110 ms each. IMPORTANT: alternate support: NEAR leg leads in 0, FAR leg leads in 4. Frames 2/6 are single-support passing with opposite boot visibly lifted. Same frame scale; retain large margins from input 1. Stance boots move RIGHT by four native cells each frame, restoring leftward travel; no skating. Ground near=111, far=108. Pelvis absorbs load then rises 2-4 cells, subtle support sway, arms and equipment counterbalance. No duplicated endpoint, no frozen torso, no eight similar standing poses. Do not reproduce guide lines, orange/cyan colors, or text.'
s['poses']=[
 'NEAR CONTACT: near leg forward/LEFT ankle x=50 y=106, sole at111; far trails x=66 y=103. Load transfers to near foot. Pelvis y=65.',
 'NEAR LOAD: near boot planted ankle x=54 y=106, knee flexes, pelvis drops y=67; far heel lifts at x=70, recovery begins.',
 'NEAR PASS: near boot planted x=58 y=106. Pelvis y=65 over near support. Far knee bends, far boot x=64 y=97 visibly airborne.',
 'NEAR PUSH: near ankle x=62 y=104, heel lifts. Pelvis y=63. Far leg reaches LEFT ankle x=54 y=99, ready to land. Continuous into4.',
 'FAR CONTACT: FAR leg now forward/LEFT x=50 y=103, sole108; near leg trails/RIGHT x=66 y=106. Opposite support from0. Pelvis y=65.',
 'FAR LOAD: far boot planted x=54 y=103, knee flexed; pelvis y=67. Near heel lifts atx=70. Equipment settles a little after body.',
 'FAR PASS: far stance x=58 y=103. Pelvis y=65 over far support. Near leg swings bent through x=64 y=100, boot off floor.',
 'FAR PUSH: far heel lifts ankle x=62 y=101, pelvis y=63. Near leg reaches LEFT x=54 y=102 to land in0. No resting/reset pose.'
]
s['root_offsets']=[[-4*i,0] for i in range(8)]
(HERE/'spec-v3.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
S=4
im=Image.new('RGB',(512*S,256*S),'#f4f3ed');d=ImageDraw.Draw(im)
font=ImageFont.truetype('/System/Library/Fonts/Monaco.ttf',12)
near_x=[50,54,58,62,66,70,64,54];far_x=[66,70,64,54,50,54,58,62]
near_y=[106,106,106,104,106,102,100,102];far_y=[103,99,97,99,103,103,103,101]
ys=[65,67,65,63,65,67,65,63];sways=[0,-1,-1,0,0,1,1,0]
records=[]
for i in range(8):
 ox=i%4*128;oy=i//4*128
 def pt(p):return((p[0]+ox)*S,(p[1]+oy)*S)
 def line(points,c,w=1):d.line([pt(p) for p in points],fill=c,width=w*S)
 def dot(p,c,r=1.4):
  x,y=pt(p);d.ellipse((x-r*S,y-r*S,x+r*S,y+r*S),fill=c)
 def knee(hip,ankle):
  dx=ankle[0]-hip[0];dy=ankle[1]-hip[1];dist=math.hypot(dx,dy);off=math.sqrt(max(0,21**2-(dist/2)**2))
  return[(hip[0]+ankle[0])/2-dy/dist*off,(hip[1]+ankle[1])/2+dx/dist*off]
 y=ys[i];sx=sways[i];pelvis=[65+sx,y];neck=[66+sx*.5,y-19];head=[66+sx*.5,y-28]
 nh=[60+sx,y+1];fh=[70+sx,y];na=[near_x[i],near_y[i]];fa=[far_x[i],far_y[i]]
 line([[4,111],[124,111]],'#c3c0b7');line([[4,108],[124,108]],'#dedbd2')
 d.text(((ox+4)*S,(oy+3)*S),f'{i} '+['NEAR lands','NEAR loads','NEAR support','FAR reaches','FAR lands','FAR loads','FAR support','NEAR reaches'][i],font=font,fill='#222222')
 line([fh,knee(fh,fa),fa],'#168db2',2);line([nh,knee(nh,na),na],'#d36d13',2)
 for an,c,fy,base in[(fa,'#168db2',108,103),(na,'#d36d13',111,106)]:
  lift=min(0,an[1]-base);ball=[an[0]-5,fy+lift];heel=[an[0]+3,an[1]+4]
  line([heel,an,ball],c);dot(ball,c)
 line([nh,pelvis,fh],'#333333');line([pelvis,neck,head],'#333333',2)
 line([[55+sx*.5,y-18],neck,[76+sx*.5,y-18]],'#555555')
 line([[55+sx*.5,y-18],[52+sx*.5,y-6],[49+sx*.5,y+6]],'#555555')
 line([[76+sx*.5,y-18],[80+sx*.5,y-7],[82+sx*.5,y-2]],'#555555')
 dot(pelvis,'#222222',2);dot(head,'#222222',2);line([[62,24],[70,24]],'#888888')
 records.append({'frame':i,'pelvis':pelvis,'near_ankle':na,'far_ankle':fa})
im.save(HERE/'pose-constraints-v3.png')
(HERE/'pose-constraints-v3.json').write_text(json.dumps({'role':'AUTHORED motion constraints only, not observations, not knight artwork. Orange near leg, cyan far leg. New leftward intention chosen before third generation; numeric acceptance thresholds unchanged.','frames':records},indent=2)+'\n')
