// Canvas-based WYSIWYG implementation (port from zns-chatbot version)
Telegram.WebApp.ready();
Telegram.WebApp.expand();

const ETransform = [[1,0,0],[0,1,0]]; // [[a,c,e],[b,d,f]]

// DOM
const help_div = document.querySelector('.help');
const screen_size_source = document.querySelector('.photo');
const photoEl = document.querySelector('.photo img');
const frameSourceEl = document.querySelector('.frame_source');
const overlayEl = document.querySelector('.overlay');

// Canvas viewer
const DPR = Math.max(1, window.devicePixelRatio||1);
const viewer = document.createElement('canvas');
viewer.className = 'viewer-canvas';
Object.assign(viewer.style, {position:'fixed',inset:'0',width:'100vw',height:'100vh',zIndex:'0'});
document.body.appendChild(viewer);
const vctx = viewer.getContext('2d');
let offscreen = document.createElement('canvas');
let offctx = offscreen.getContext('2d');

// State
let W=0,H=0,Vmin=0; // viewport
let frame_size=0,f_left=0,f_top=0; // CSS px
let pw=0,ph=0; // photo intrinsic
let transformationMatrix = ETransform; // in real frame units
const alignment = {x:0,y:0,changed:false,scale:{x:1,y:1}}; // optional realign

if (Telegram.WebApp.platform === 'tdesktop') help_div.innerText = help_desktop; else help_div.innerText = help_mobile;

// Matrix helpers
function M(A,B){return [[A[0][0]*B[0][0]+A[0][1]*B[1][0], A[0][0]*B[0][1]+A[0][1]*B[1][1], A[0][0]*B[0][2]+A[0][1]*B[1][2]+A[0][2]], [A[1][0]*B[0][0]+A[1][1]*B[1][0], A[1][0]*B[0][1]+A[1][1]*B[1][1], A[1][0]*B[0][2]+A[1][1]*B[1][2]+A[1][2]]];}
function MM(...m){if(!m.length) return ETransform; let r=m[0]; for(let i=1;i<m.length;i++) r=M(r,m[i]); return r;}
function translate2matrix(x,y){return [[1,0,x],[0,1,y]];}
function scale2matrix(sx,sy){return [[sx,0,0],[0,sy,0]];}
function rotate2matrix(t){const c=Math.cos(t),s=Math.sin(t);return [[c,-s,0],[s,c,0]];}
function decompose(T){const [a,c,e]=T[0]; const [b,d,f]=T[1]; const sx=Math.hypot(a,c); const sy=Math.hypot(b,d); const rot=Math.atan2(b,a); return {scaling:{x:sx,y:sy}, rotation:rot, translation:{x:e,y:f}};}

// Coordinate conversions
function viewportDeltaToReal(dx_css,dy_css){const factor = real_frame_size / frame_size; return [dx_css*factor, dy_css*factor];}
function viewportPointToReal(x_css,y_css){const cx=f_left+frame_size/2; const cy=f_top+frame_size/2; const factor = real_frame_size / frame_size; return [(x_css-cx)*factor,(y_css-cy)*factor];}

function recalcLayout(){
    W = screen_size_source.clientWidth; H = screen_size_source.clientHeight; Vmin=Math.min(W,H);
    frame_size = Vmin; f_left=(W-frame_size)/2; f_top=(H-frame_size)/2;
    // resize canvases
    viewer.width = Math.max(1, Math.round(W*DPR)); viewer.height=Math.max(1, Math.round(H*DPR)); viewer.style.width=W+'px'; viewer.style.height=H+'px';
    const sqPx = Math.max(1, Math.round(frame_size*DPR)); offscreen.width=sqPx; offscreen.height=sqPx;
    draw();
}

function initPhoto(){ if(!photoEl.naturalWidth||!photoEl.naturalHeight) return; if(pw===photoEl.naturalWidth && ph===photoEl.naturalHeight) return; pw=photoEl.naturalWidth; ph=photoEl.naturalHeight; const smaller=Math.min(pw,ph); const F = real_frame_size / smaller; transformationMatrix = [[F,0,0],[0,F,0]]; draw(); }

function renderToSquare(ctx){const size=ctx.canvas.width; ctx.clearRect(0,0,size,size); ctx.save(); ctx.translate(size/2,size/2); const S = size/real_frame_size; ctx.scale(S,S); const d=decompose(transformationMatrix); ctx.translate(d.translation.x+alignment.x,d.translation.y+alignment.y); ctx.scale(d.scaling.x,d.scaling.y); ctx.rotate(d.rotation); ctx.drawImage(photoEl,-pw/2,-ph/2,pw,ph); ctx.restore(); if(frameSourceEl && frameSourceEl.complete){ ctx.drawImage(frameSourceEl,0,0,size,size); }}
function draw(){ if(!frame_size) return; renderToSquare(offctx); vctx.clearRect(0,0,viewer.width,viewer.height); const dx=Math.round(f_left*DPR), dy=Math.round(f_top*DPR); vctx.drawImage(offscreen,dx,dy); }

// Interaction
let isMouseDown=false,lastX=0,lastY=0; let initialTouchDist=0, initialTouchAngle=0;
function movePhoto(dx,dy){const [rx,ry]=viewportDeltaToReal(dx,dy); transformationMatrix = M(translate2matrix(rx,ry), transformationMatrix); draw();}
function rotatePhoto(angle,pivotX_css,pivotY_css){const [px,py]=viewportPointToReal(pivotX_css,pivotY_css); const R = MM(translate2matrix(px,py), rotate2matrix(angle), translate2matrix(-px,-py)); transformationMatrix = M(R, transformationMatrix); draw();}
function scalePhoto(k,pivotX_css,pivotY_css){const [px,py]=viewportPointToReal(pivotX_css,pivotY_css); const S = MM(translate2matrix(px,py), scale2matrix(k,k), translate2matrix(-px,-py)); transformationMatrix = M(S, transformationMatrix); draw();}

function onMouseDown(e){e.preventDefault(); isMouseDown=true; lastX=e.clientX; lastY=e.clientY;}
function onMouseMove(e){ if(!isMouseDown) return; e.preventDefault(); const dx=e.clientX-lastX, dy=e.clientY-lastY; if(e.shiftKey){ const angle=Math.atan2(dy,dx); rotatePhoto(angle,e.clientX,e.clientY);} else { movePhoto(dx,dy); lastX=e.clientX; lastY=e.clientY;} }
function onMouseUp(e){e.preventDefault(); isMouseDown=false;}
function onMouseWheel(e){e.preventDefault(); const step=e.shiftKey?0.005:0.1; const k=(e.deltaY<0)?(1+step):(1-step); scalePhoto(k,e.clientX,e.clientY);} 

function getTouches(e){return Array.from(e.touches).map(t=>({x:t.clientX,y:t.clientY}));}
function onTouchStart(e){e.preventDefault(); if(e.touches.length===1){ isMouseDown=true; lastX=e.touches[0].clientX; lastY=e.touches[0].clientY; } else if(e.touches.length===2){ isMouseDown=false; const [t1,t2]=getTouches(e); initialTouchDist=Math.hypot(t2.x-t1.x,t2.y-t1.y); initialTouchAngle=Math.atan2(t2.y-t1.y,t2.x-t1.x);} }
function onTouchMove(e){e.preventDefault(); if(e.touches.length===1 && isMouseDown){ const t=e.touches[0]; movePhoto(t.clientX-lastX, t.clientY-lastY); lastX=t.clientX; lastY=t.clientY; } else if(e.touches.length===2){ const [t1,t2]=getTouches(e); const dist=Math.hypot(t2.x-t1.x,t2.y-t1.y); const scale=dist/initialTouchDist; const angle=Math.atan2(t2.y-t1.y,t2.x-t1.x)-initialTouchAngle; // apply combined
    const centerX=(t1.x+t2.x)/2, centerY=(t1.y+t2.y)/2; const C = MM(translate2matrix(...viewportPointToReal(centerX,centerY)), rotate2matrix(angle), scale2matrix(scale,scale), translate2matrix(...viewportDeltaToReal(-centerX+centerX,-centerY+centerY))); // simplified rotate then scale
    // simpler approach: rotate + scale around center by composing separate operations
    rotatePhoto(angle, centerX, centerY); scalePhoto(scale, centerX, centerY); initialTouchDist=dist; initialTouchAngle+=angle; }
}
function onTouchEnd(e){e.preventDefault(); if(e.touches.length===0) isMouseDown=false; }

// Debug remotejs minimal
(function debugInit(){ let DEBUG=false; let countdown=10; const dbg=document.querySelector('.debug-layer'); if(!dbg) return; const remoteBtn=dbg.querySelector('.remotejs'); const input=dbg.querySelector('input[name=remotejs]'); if(input) input.value=debug_code; function enable(){ if(DEBUG) return; DEBUG=true; document.body.classList.add('debug'); remoteBtn?.addEventListener('click',()=>{ const val=input.value.trim(); if(/^[0-9a-f-]{36}$/.test(val)){ let s=document.createElement('script'); s.src='https://remotejs.com/agent/agent.js'; s.dataset.consolejsChannel=val; document.head.appendChild(s); } }); }
    document.addEventListener('contextmenu',e=>{ if(e.altKey && !DEBUG){ if(--countdown<=0) enable(); e.preventDefault(); }}); document.body.addEventListener('touchstart',e=>{ if(!DEBUG && e.touches.length===5){ if(--countdown<=0) enable(); }} ,{capture:true}); })();

// Wire up
viewer.addEventListener('mousedown', onMouseDown);
window.addEventListener('mousemove', onMouseMove);
window.addEventListener('mouseup', onMouseUp);
viewer.addEventListener('wheel', onMouseWheel, {passive:false});
viewer.addEventListener('touchstart', onTouchStart, {passive:false});
viewer.addEventListener('touchmove', onTouchMove, {passive:false});
viewer.addEventListener('touchend', onTouchEnd, {passive:false});
window.addEventListener('resize', ()=>{recalcLayout();});
photoEl.addEventListener('load', ()=>{initPhoto(); draw();});

function exportData(){
    // Render the transformed photo at full resolution and upload it.
    const exportCanvas=document.createElement('canvas');
    exportCanvas.width=real_frame_size; exportCanvas.height=real_frame_size;
    const ect=exportCanvas.getContext('2d');
    (function render(){
        const size=exportCanvas.width; ect.clearRect(0,0,size,size); ect.save(); ect.translate(size/2,size/2); const S=size/real_frame_size; ect.scale(S,S); const d=decompose(transformationMatrix); ect.translate(d.translation.x+alignment.x,d.translation.y+alignment.y); ect.scale(d.scaling.x,d.scaling.y); ect.rotate(d.rotation); ect.drawImage(photoEl,-pw/2,-ph/2,pw,ph); ect.restore(); })();
    const dataUrl = exportCanvas.toDataURL('image/png');
    fetch(`/fit_frame?id=${encodeURIComponent(photo_id)}`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:photo_id,image:dataUrl})})
        .then(r=>{ if(!r.ok) throw new Error('upload failed'); return r.json(); })
        .then(()=>{ Telegram.WebApp.sendData(JSON.stringify({id:photo_id, uploaded:true})); Telegram.WebApp.close(); })
        .catch(err=>{ console.error('Upload failed', err); alert('Upload failed, please try again.'); });
}
Telegram.WebApp.MainButton.setText(finish_button_text);
Telegram.WebApp.MainButton.show();
Telegram.WebApp.MainButton.onClick(()=>exportData());
Telegram.WebApp.BackButton.onClick(()=>Telegram.WebApp.close());
Telegram.WebApp.BackButton.show();

// Init when ready
function whenReady(){ if(photoEl.complete) {initPhoto(); recalcLayout();} else photoEl.addEventListener('load', ()=>{initPhoto(); recalcLayout();}); if(frameSourceEl && !frameSourceEl.complete) frameSourceEl.addEventListener('load', draw); else draw(); }
whenReady();
