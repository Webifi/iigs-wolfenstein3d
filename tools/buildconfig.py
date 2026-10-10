"""Selected asset floor and offline presentation choices."""
import json
from wolfdata import ROOT

def config():
    p=ROOT/'build/gen/config.json'
    return json.loads(p.read_text()) if p.exists() else dict(floor=1,colors='four',pixels='pair',shading=6)
