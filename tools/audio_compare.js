// The established comparison player, with local script payloads replacing
// fetch so its shared-clock Web Audio playback also works from disk.
const catalog = JSON.parse(document.getElementById('recordings').textContent);
const ctx = new (window.AudioContext || window.webkitAudioContext)();
const $ = id => document.getElementById(id);
let song = 0, active = 'A', bufs = {}, gains = {}, srcs = {}, playing = false;
let startAt = 0, offset = 0, token = 0, peaks = {}, levels = {};
const pending = new Map();
window.audioFileLoaded = (identity, encoded) => {
  const waiting = pending.get(identity);
  if (waiting) {
    pending.delete(identity);
    const binary = atob(encoded), bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    waiting.resolve(bytes.buffer);
  }
};
function wavBytes(version) {
  const identity = version.provenance.wav_sha256;
  let waiting = pending.get(identity);
  if (!waiting) {
    let resolve, reject;
    const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
    waiting = {promise, resolve};
    pending.set(identity, waiting);
    const script = document.createElement('script');
    script.src = version.payload;
    script.onload = () => {
      script.remove();
      if (pending.has(identity)) { pending.delete(identity); reject(new Error('Invalid WAV payload: '+version.payload)); }
    };
    script.onerror = () => { pending.delete(identity); script.remove(); reject(new Error('Missing WAV payload: '+version.payload)); };
    document.head.append(script);
  }
  // decodeAudioData takes ownership of its buffer. Concurrent comparisons
  // of identical recordings each receive their own bytes.
  return waiting.promise.then(bytes => bytes.slice(0));
}
const fmt = x => { x = Math.max(0, x || 0); return Math.floor(x / 60) + ':' + String(Math.floor(x % 60)).padStart(2, '0'); };
function dur() { return Math.max(0, ...Object.values(bufs).map(b => b.duration)); }
function pos() { return playing ? Math.max(0, Math.min(dur(), ctx.currentTime - startAt)) : offset; }
function stopAll() { Object.values(srcs).forEach(s => { try { s.stop(); } catch (e) {} }); srcs = {}; }
function startAll(at) {
  stopAll();
  const t0 = ctx.currentTime + 0.05;
  for (const [k, b] of Object.entries(bufs)) {
    if (!gains[k]) { gains[k] = ctx.createGain(); gains[k].connect(ctx.destination); }
    gains[k].gain.value = k === active ? 1 : 0;
    const s = ctx.createBufferSource(); s.buffer = b; s.connect(gains[k]);
    s.start(t0, Math.min(at, b.duration)); srcs[k] = s;
  }
  startAt = t0 - at; playing = true; $('play').innerHTML = '&#10074;&#10074;';
  $('status').textContent = 'Playing · recorded levels unchanged';
}
function pause() { offset = pos(); stopAll(); playing = false; $('play').innerHTML = '&#9654;'; }
async function toggle() {
  if (!Object.keys(bufs).length) return;
  if (playing) { pause(); $('status').textContent = 'Paused'; return; }
  try { const generation = token; await ctx.resume(); if (generation === token) startAll(offset >= dur() ? 0 : offset); }
  catch (e) { $('status').textContent = 'Could not play: '+e.message; }
}
function seek(t) { t = Math.max(0, Math.min(dur(), t)); if (playing) startAll(t); else offset = t; draw(); }
function select(k) {
  if (!bufs[k]) return; active = k;
  for (const [kk, g] of Object.entries(gains)) { g.gain.cancelScheduledValues(ctx.currentTime); g.gain.setValueAtTime(kk === k ? 1 : 0, ctx.currentTime); }
  document.querySelectorAll('.ver').forEach(d => { d.classList.toggle('on', d.dataset.k === k); d.setAttribute('aria-pressed', d.dataset.k === k); });
  drawWave();
}
function db(b) {
  let pk = 0, sum = 0, n = 0;
  for (let c = 0; c < b.numberOfChannels; c++) {
    const d = b.getChannelData(c);
    for (const v of d) { pk = Math.max(pk, Math.abs(v)); sum += v*v; n++; }
  }
  return [20*Math.log10(pk || 1e-9), 10*Math.log10(sum/n || 1e-12)];
}
function setLevels() {
  for (const [k,v] of Object.entries(levels)) {
    const el = document.querySelector('.ver[data-k="'+k+'"] .lvl');
    if (el) el.textContent = 'WAV RMS '+v[1].toFixed(1)+' dBFS · peak '+v[0].toFixed(1)+' dBFS · player gain 0 dB';
  }
}
function mkPeaks(b, w) {
  const d = b.getChannelData(0), out = new Float32Array(w), step = Math.max(1, Math.floor(d.length/w));
  for (let x=0; x<w; x++) { let m=0; for (let i=x*step; i<(x+1)*step && i<d.length; i+=8) m=Math.max(m,Math.abs(d[i])); out[x]=m; }
  return out;
}
function drawWave() {
  const cv=$('wave'), r=cv.getBoundingClientRect(), dpr=window.devicePixelRatio || 1;
  cv.width=r.width*dpr; cv.height=r.height*dpr; const g=cv.getContext('2d'); g.clearRect(0,0,cv.width,cv.height);
  const b=bufs[active]; if (!b) return;
  const key=song+active+cv.width; if (!peaks[key]) peaks[key]=mkPeaks(b,cv.width);
  const p=peaks[key], mid=cv.height/2, scale=b.duration/dur();
  g.fillStyle={A:'#f2683c', B:'#4f8cff', C:'#2fc76b', D:'#b896ee'}[active];
  for (let x=0; x<p.length; x++) { const h=p[x]*mid; g.fillRect(x*scale,mid-h,1,Math.max(1,2*h)); }
}
function draw() {
  const d=dur(), t=pos(); $('head').style.left=(d ? 100*t/d : 0)+'%'; $('time').textContent=fmt(t)+' / '+fmt(d);
  $('track').setAttribute('aria-valuemax', d); $('track').setAttribute('aria-valuenow', t);
}
function buildSongs() {
  $('songs').replaceChildren();
  const sections=new Map(), groups=new Map();
  catalog.items.forEach((row,i) => {
    const section=row.section || 'Music';
    if(!sections.has(section)) {
      const div=document.createElement('div'), heading=document.createElement('h2'); heading.textContent=section; div.append(heading); $('songs').append(div); sections.set(section,div);
    }
    let parent=sections.get(section);
    if(row.song) {
      const key=section+':'+row.song_id+':'+row.song;
      if(!groups.has(key)) {
        const group=document.createElement('details'), heading=document.createElement('summary');
        group.className='song'; heading.textContent=row.song; group.append(heading); parent.append(group); groups.set(key,group);
      }
      parent=groups.get(key); if(i===song)parent.open=true;
    }
    const b=document.createElement('button'); b.textContent=row.part || row.label;
    if(row.status && row.status!=='ready')b.textContent+=' · '+row.status;
    b.className=i===song?'on':''; b.setAttribute('aria-current',i===song); b.onclick=()=>load(i); parent.append(b);
  });
}
function buildVers() {
  $('vers').replaceChildren(); const row=catalog.items[song]; $('vers').style.setProperty('--versions',row.versions.length);
  row.versions.forEach((v,i) => {
    const available=v.status!=='unavailable';
    const k=String.fromCharCode(65+i), d=document.createElement('div'); d.className='ver '+k+(k===active?' on':''); d.dataset.k=k;
    d.setAttribute('role','button'); d.tabIndex=available?0:-1; d.setAttribute('aria-label',k+' · '+v.label); d.setAttribute('aria-pressed',k===active); d.setAttribute('aria-disabled',!available);
    const letter=document.createElement('div'); letter.className='k'; letter.textContent=k;
    const name=document.createElement('div'); name.className='n'; name.textContent=v.label;
    const level=document.createElement('div'); level.className='lvl'; level.textContent=available?'loading':v.reason;
    d.append(letter,name,level); d.onclick=()=>select(k); d.onkeydown=e=>{if(e.key==='Enter')select(k);}; $('vers').append(d);
  });
}
async function load(index) {
  const my=++token; pause(); offset=0; bufs={}; levels={}; peaks={}; song=index;
  const row=catalog.items[index]; active=String.fromCharCode(65+(row.default_version || 0)); $('play').disabled=true;
  $('title').textContent=row.label; $('note').textContent=row.note; buildSongs(); buildVers(); drawWave(); draw();
  $('render-gain').textContent=row.versions.map(v=>v.label+': '+v.kind+(v.provenance.build_status?' · '+v.provenance.build_status:'')).join('. ');
  $('status').textContent='Loading comparison WAVs…'; $('downloads').replaceChildren(); $('files').replaceChildren();
  if(!row.versions.length) { $('status').textContent=row.status==='failed'?'Generation failed — see build log':row.status==='unavailable'?'No recording generated for this build':'Generation pending'; $('render-gain').textContent='No recording has been substituted.'; return; }
  row.versions.forEach(v=>{
    if(v.status==='unavailable')return;
    const p=document.createElement('p'), link=document.createElement('a'); link.href=v.file; link.textContent=v.label+' — original WAV'; p.append(link); $('downloads').append(p);
    const pre=document.createElement('pre'); pre.textContent=JSON.stringify(v.provenance,null,2); $('files').append(pre);
  });
  try {
    const available=row.versions.map((v,i)=>[v,i]).filter(([v])=>v.status!=='unavailable');
    if(!available.length) { $('status').textContent='No recordings available for this build'; return; }
    const got=await Promise.all(available.map(async([v,i])=>[String.fromCharCode(65+i), await ctx.decodeAudioData(await wavBytes(v))]));
    if (my!==token) return;
    got.forEach(([k,b])=>{bufs[k]=b; levels[k]=db(b);}); setLevels(); $('play').disabled=false;
    $('status').textContent='Ready · '+got.length+' WAVs loaded'; select(bufs[active]?active:got[0][0]); draw();
  } catch(e) { if(my===token)$('status').textContent='Could not load: '+e.message; }
}
$('play').onclick=toggle;
$('track').onclick=e=>{const r=e.currentTarget.getBoundingClientRect(); seek(dur()*(e.clientX-r.left)/r.width);};
document.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey||['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;
  const k=e.key.toLowerCase();
  if(/^[a-d]$/.test(k))select(k.toUpperCase()); else if(/^[1-4]$/.test(k))select(String.fromCharCode(64+Number(k)));
  else if(e.key===' '){e.preventDefault();toggle();} else if(e.key==='ArrowLeft'){e.preventDefault();seek(pos()-5);} else if(e.key==='ArrowRight'){e.preventDefault();seek(pos()+5);}
});
window.addEventListener('resize',drawWave);
setInterval(()=>{draw();if(playing&&pos()>=dur())pause();},50);
document.title=catalog.title; load(0);
