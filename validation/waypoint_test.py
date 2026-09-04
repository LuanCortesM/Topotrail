"""A travessia com os cumes declarados como destinos intermediarios.

Se a concordancia saltar, a explicacao de "incompatibilidade de objetivo" fica
confirmada: o modelo estava certo e faltava dizer a ele o que se queria. Se nao
saltar, era defeito do modelo e a explicacao anterior estava errada.
"""
import sys, numpy as np, tracks, speed_slope as ss, importlib.util
import xml.etree.ElementTree as ET
from osgeo import gdal; gdal.UseExceptions()
sys.path.insert(0, "/home/claude/work/repo/tests")
import conftest; conftest._install_stubs()
alg = sys.modules["tt_algorithm"]
def load(n):
    s=importlib.util.spec_from_file_location(n,f"/home/claude/work/repo/processing/{n}.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
terrain = load("terrain")
from geom import densify, agreement

K='/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste/travessia-marins-itaguare.kml'
loc=lambda t: t.rsplit('}',1)[-1]
named={}
for pm in ET.parse(K).getroot().iter():
    if loc(pm.tag)!='Placemark': continue
    name=next((c.text for c in pm if loc(c.tag)=='name'), None)
    pt=next((e for e in pm.iter() if loc(e.tag)=='Point'), None)
    if pt is None or not name: continue
    c=next((e.text for e in pt if loc(e.tag)=='coordinates'), '').strip().split(',')
    named[name]=(float(c[0]), float(c[1]))

lon,lat,ele,_ = max(tracks.read_any(K), key=lambda t: len(t[0]))
dem = ss.Dem("mantiqueira_utm23s.tif")
tx,ty = map(np.asarray, ss.project(lon,lat,dem.epsg))
rx,ry,real_len = densify(tx,ty,10.)
pad=2000.
gdal.Warp("/tmp/wp.tif","mantiqueira_utm23s.tif",
          outputBounds=(tx.min()-pad,ty.min()-pad,tx.max()+pad,ty.max()+pad),dstNodata=-9999)
d=gdal.Open("/tmp/wp.tif"); gt=d.GetGeoTransform()
z=d.GetRasterBand(1).ReadAsArray().astype(np.float32); z[z==-9999]=np.nan
slope,ch,cv = terrain.derive_terrain(z,gt)
score=np.where(np.isfinite(z),(alg.normalize_cost(slope,0.,50.)
      +alg.normalize_curvature_preference(ch)+alg.normalize_curvature_preference(cv))/3.,np.nan)
cost = alg.build_route_cost(score, alg.ROUTE_COST_TOBLER, 6.0)

def rc_of(lonlat):
    x,y = ss.project(np.array([lonlat[0]]), np.array([lonlat[1]]), dem.epsg)
    return (int((y[0]-gt[3])/gt[5]), int((x[0]-gt[0])/gt[1]))
start, end = (int((ty[0]-gt[3])/gt[5]), int((tx[0]-gt[0])/gt[1])), \
             (int((ty[-1]-gt[3])/gt[5]), int((tx[-1]-gt[0])/gt[1]))
straight = np.hypot(tx[-1]-tx[0], ty[-1]-ty[0])
BUF=[60,150,250,500]

def report(label, path):
    px = gt[0]+(np.array([p[1] for p in path])+.5)*gt[1]
    py = gt[3]+(np.array([p[0] for p in path])+.5)*gt[5]
    mx,my,mlen = densify(px,py,10.)
    a,dmin = agreement(rx,ry,mx,my,BUF)
    prof = z[np.clip(((my-gt[3])/gt[5]).astype(int),0,z.shape[0]-1),
             np.clip(((mx-gt[0])/gt[1]).astype(int),0,z.shape[1]-1)]
    gain = float(np.nansum(np.clip(np.diff(prof),0,None)))
    print(f"{label:38s} {mlen/1000:6.2f} " + " ".join(f"{100*v:6.1f}%" for v in a)
          + f" {np.median(dmin):7.0f}m {np.nanmax(prof):6.0f}m {gain:7.0f}m")

print(f"{'modelo':38s} {'km':>6s} " + " ".join(f"{'<'+str(b)+'m':>7s}" for b in BUF)
      + f" {'desv.med':>8s} {'cume':>6s} {'subida':>7s}")
sx=np.linspace(tx[0],tx[-1],600); sy=np.linspace(ty[0],ty[-1],600)
a,ds = agreement(rx,ry,sx,sy,BUF)
print(f"{'LINHA RETA (controle)':38s} {straight/1000:6.2f} "
      + " ".join(f"{100*v:6.1f}%" for v in a) + f" {np.median(ds):7.0f}m")

p,_ = alg.least_cost_path(cost,start,end,elevation=z.astype(np.float64),
                          pixel_size_m=gt[1],anisotropic=True)
report("plugin: so origem e destino", p)

for label, names in (
    ("plugin: + Pico do Marins", ["Pico do Marins"]),
    ("plugin: + Marins, Marinzinho", ["Pico do Marins","Pico do Marinzinho"]),
    ("plugin: + Marins, Marinzinho, Itaguare",
     ["Pico do Marins","Pico do Marinzinho","Pico Itaguaré"])):
    wps = [start] + [rc_of(named[n]) for n in names] + [end]
    cells,total,legs = alg.multi_leg_route(cost, wps, elevation=z.astype(np.float64),
                                           pixel_size_m=gt[1], anisotropic=True)
    report(label, cells)

zr = z[np.clip(((ry-gt[3])/gt[5]).astype(int),0,z.shape[0]-1),
       np.clip(((rx-gt[0])/gt[1]).astype(int),0,z.shape[1]-1)]
print(f"{'TRILHA REAL':38s} {real_len/1000:6.2f} " + " "*33
      + f" {'--':>7s}  {np.nanmax(zr):6.0f}m {float(np.nansum(np.clip(np.diff(zr),0,None))):7.0f}m")
