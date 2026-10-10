"""Empty rectangles provide exact positive CheckLine results."""
import struct

def partition(tilemap):
 remaining=[[tilemap[x*64+y]==0 for x in range(64)] for y in range(64)]
 result=[]
 while True:
  heights=[0]*64;best=(0,0,0,0,0)
  for y,row in enumerate(remaining):
   heights=[h+1 if empty else 0 for h,empty in zip(heights,row)]
   stack=[]
   for x,h in enumerate(heights+[0]):
    start=x
    while stack and stack[-1][1]>h:
     a,k=stack.pop();start=a
     candidate=((x-a)*k,a,x-1,y-k+1,y)
     if candidate>best:best=candidate
    if not stack or stack[-1][1]<h:stack.append((start,h))
  area,x0,x1,y0,y1=best
  if not area:break
  result.append((x0,x1,y0,y1))
  for y in range(y0,y1+1):
   for x in range(x0,x1+1):remaining[y][x]=False
 return result


def encode(tilemap, *, allow_partial=False):
    rectangles=partition(tilemap)
    if allow_partial:
        # This is only a positive visibility shortcut. Unlisted cells keep
        # region zero and use the original exact CheckLine traversal.
        rectangles=rectangles[:254]
    else:
        assert len(rectangles)<=254
    ids=bytearray(4096)
    packed=bytearray(struct.pack('<H',len(rectangles)))
    for number,(x0,x1,y0,y1) in enumerate(rectangles,1):
        packed.extend((x0,x1,y0,y1))
        for x in range(x0,x1+1):
            for y in range(y0,y1+1):
                cell=x*64+y
                assert not tilemap[cell] and not ids[cell]
                ids[cell]=number
    assert all(not ids[i] or tile==0 for i,tile in enumerate(tilemap))
    if not allow_partial:
        assert all(bool(ids[i])==(tile==0) for i,tile in enumerate(tilemap))
    packed.extend(bytes(1024-len(packed)))
    return bytes(packed),bytes(ids),rectangles
