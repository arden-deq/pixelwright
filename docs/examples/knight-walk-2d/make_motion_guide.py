"""Draw declared 2D constraints, never artwork observations or knight artwork."""
from pathlib import Path
import json, math
from PIL import Image, ImageDraw, ImageFont
HERE=Path(__file__).resolve().parent
S=4
im=Image.new('RGB',(512*S,256*S),'#f4f3ed')
d=ImageDraw.Draw(im)
font=ImageFont.truetype('/System/Library/Fonts/Monaco.ttf',11)
near_x=[78,74,70,66,62,58,64,74]
far_x=[62,58,64,74,78,74,70,66]
near_y=[106,106,106,104,106,102,100,102]
far_y=[103,99,97,99,103,103,103,101]
hip_y=[65,67,65,63,65,67,65,63]
sway=[0,1,1,0,0,-1,-1,0]
records=[]
for i in range(8):
 ox=(i%4)*128;oy=(i//4)*128
 def pt(p): return ((p[0]+ox)*S,(p[1]+oy)*S)
 def line(points,color,width=1): d.line([pt(p) for p in points],fill=color,width=width*S)
 def dot(p,color,r=1.3):
  x,y=pt(p);d.ellipse((x-r*S,y-r*S,x+r*S,y+r*S),fill=color)
 def knee(hip,ankle):
  a=b=21.;dx=ankle[0]-hip[0];dy=ankle[1]-hip[1];dist=math.hypot(dx,dy)
  mid=((hip[0]+ankle[0])/2,(hip[1]+ankle[1])/2)
  off=math.sqrt(max(0,a*a-(dist/2)**2))
  return [mid[0]+dy/dist*off,mid[1]-dx/dist*off]
 y=hip_y[i];sx=sway[i]
 pelvis=[65+sx,y];neck=[66+sx*.5,y-19];head=[66+sx*.5,y-28]
 near_hip=[70+sx,y+1];far_hip=[60+sx,y]
 near_ankle=[near_x[i],near_y[i]];far_ankle=[far_x[i],far_y[i]]
 line([[4,111],[124,111]],'#c3c0b7')
 line([[4,108],[124,108]],'#dedbd2')
 d.text(((ox+4)*S,(oy+3)*S),f'{i}: '+['near contact','near load','near passing','near push','far contact','far load','far passing','far push'][i],fill='#333333',font=font,stroke_width=0)
 line([far_hip,knee(far_hip,far_ankle),far_ankle],'#168db2',2)
 line([near_hip,knee(near_hip,near_ankle),near_ankle],'#d36d13',2)
 for ankle,color,floor in [(far_ankle,'#168db2',108),(near_ankle,'#d36d13',111)]:
  lift=ankle[1]-(103 if color=='#168db2' else 106)
  ball=[ankle[0]+5,floor+min(0,lift)]
  heel=[ankle[0]-3,ankle[1]+4]
  line([heel,ankle,ball],color,1)
  dot(ball,color,1)
 line([near_hip,pelvis,far_hip],'#333333',1)
 line([pelvis,neck,head],'#333333',2)
 line([[55+sx*.5,y-18],neck,[76+sx*.5,y-18]],'#555555')
 line([[55+sx*.5,y-18],[52+sx*.5,y-6],[49+sx*.5,y+6]],'#555555')
 line([[76+sx*.5,y-18],[80+sx*.5,y-7],[82+sx*.5,y-2]],'#555555')
 dot(pelvis,'#333333',2);dot(head,'#333333',2)
 records.append({'frame':i,'pelvis':pelvis,'near_ankle':near_ankle,'far_ankle':far_ankle,'note':'Authored intended layout only; not measured artwork.'})
 # The small top marker shows the selected design's crown/plume height, not a mesh silhouette.
 line([[62,24],[70,24]],'#888888')
im.save(HERE/'pose-constraints.png')
(HERE/'pose-constraints.json').write_text(json.dumps({'role':'Second input: declared 2D motion placement only. Orange near leg, cyan far leg. Ignore guide colors, lines and text in final artwork. First input is selected knight appearance.','frames':records},indent=2)+'\n')
spec=json.loads((HERE/'spec.json').read_text())
spec['states']['walk']['intent'] += ' If a second image is attached, it is ONLY the simple 2D motion-placement guide: orange identifies the near leg, cyan identifies the far leg, dark dots identify pelvis/head. Follow support exchange, pose order and scale envelope from it, while drawing NEW 2D knight pixel art from the FIRST identity reference. Do not copy guide colors, lines, labels or a rigid stick-figure silhouette. The guide is not an artwork observation. IMPORTANT: leave the same large transparent margins as the selected design (plume begins around y=24, boots around y=111); do not enlarge the knight to fill each slot. Each half of the cycle must have the OPPOSITE leg forward; near foot leads in frame 0, FAR foot leads in frame 4. All eight poses must differ.'
spec['states']['walk']['poses'][0]=spec['states']['walk']['poses'][0].replace('x=54','x=62')
spec['states']['walk']['poses'][4]=spec['states']['walk']['poses'][4].replace('x=54','x=62')
(HERE/'spec-v2.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
