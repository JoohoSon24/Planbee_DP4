/* Resizable, keyboard-accessible conversation / board split. Local preferences only. */
(function(){
  'use strict';
  var app=document.querySelector('.app'),chat=document.querySelector('.chan'),board=document.querySelector('.board');if(!app||!chat||!board)return;
  var divider=document.createElement('div');divider.className='panel-divider';divider.tabIndex=0;divider.setAttribute('role','separator');divider.setAttribute('aria-orientation','vertical');
  chat.id='chat-panel';divider.setAttribute('aria-controls','chat-panel');chat.after(divider);app.classList.add('resizable-panels');
  var toggle=document.createElement('button');toggle.type='button';toggle.className='btn sm chat-toggle';toggle.setAttribute('aria-controls','chat-panel');chat.querySelector('.pane-h').append(toggle);
  var reopen=document.createElement('button');reopen.type='button';reopen.className='btn sm chat-reopen';reopen.setAttribute('aria-controls','chat-panel');board.querySelector('.pane-h').prepend(reopen);
  /* The split snaps to a few fixed ratios (chat share of the window). */
  var SNAPS=[.32,.42,.5,.6];
  var width=null,collapsed=false;try{width=Number(localStorage.getItem('pb-chat-width'))||null;collapsed=localStorage.getItem('pb-chat-collapsed')==='true';}catch(err){}
  function en(){return document.documentElement.getAttribute('data-lang')==='en';}
  function bounds(){return {min:320,max:Math.max(320,app.clientWidth-332)};}
  function save(){try{localStorage.setItem('pb-chat-width',String(width));localStorage.setItem('pb-chat-collapsed',String(collapsed));}catch(err){}}
  function draw(){
    var b=bounds();if(width===null&&window.innerWidth>900)width=app.clientWidth*.42;var actual=Math.round(Math.max(b.min,Math.min(b.max,width||app.clientWidth*.42)));
    app.style.setProperty('--chat-width',actual+'px');app.classList.toggle('chat-collapsed',collapsed);
    divider.setAttribute('aria-valuemin',b.min);divider.setAttribute('aria-valuemax',b.max);divider.setAttribute('aria-valuenow',actual);
    divider.setAttribute('aria-label',en()?'Resize chat and board. Snaps to 32 · 42 · 50 · 60%. Arrow keys move between them; Home resets.':'채팅·보드 너비 조절. 32·42·50·60%에 맞춰짐. 방향키로 이동, Home으로 초기화');
    toggle.innerHTML='<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6 2.5v11" stroke="currentColor" stroke-width="1.4"/><path d="M11 6l-2 2 2 2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';toggle.title=en()?'Hide chat':'채팅 접기';toggle.setAttribute('aria-label',toggle.title);toggle.setAttribute('aria-expanded',String(!collapsed));
    reopen.innerHTML='<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6 2.5v11" stroke="currentColor" stroke-width="1.4"/><path d="M9 6l2 2-2 2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg><span>'+(en()?'Open chat':'채팅 열기')+'</span>';reopen.hidden=!collapsed;reopen.setAttribute('aria-expanded',String(!collapsed));
  }
  reopen.onclick=function(){toggle.onclick();};
  toggle.onclick=function(){collapsed=!collapsed;draw();save();window.dispatchEvent(new Event('resize'));if(!collapsed)document.getElementById('change-input').focus();};
  divider.addEventListener('pointerdown',function(e){if(e.button!==0||window.innerWidth<=900)return;e.preventDefault();divider.setPointerCapture(e.pointerId);app.classList.add('panel-resizing');});
  divider.addEventListener('pointermove',function(e){if(!divider.hasPointerCapture(e.pointerId))return;width=e.clientX-app.getBoundingClientRect().left;draw();});
  function snap(w){var W=app.clientWidth,b=bounds(),best=null;SNAPS.forEach(function(r){var x=Math.max(b.min,Math.min(b.max,W*r));if(best===null||Math.abs(x-w)<Math.abs(best-w))best=x;});return best===null?w:best;}
  function finish(e){if(divider.hasPointerCapture(e.pointerId))divider.releasePointerCapture(e.pointerId);app.classList.remove('panel-resizing');width=snap(width||app.clientWidth*.42);app.classList.add('panel-snapping');draw();setTimeout(function(){app.classList.remove('panel-snapping');window.dispatchEvent(new Event('resize'));},220);save();}
  divider.addEventListener('pointerup',finish);divider.addEventListener('pointercancel',finish);
  divider.addEventListener('lostpointercapture',function(){app.classList.remove('panel-resizing');});
  divider.addEventListener('dblclick',function(){width=app.clientWidth*.42;draw();save();});
  divider.addEventListener('keydown',function(e){if(!['ArrowLeft','ArrowRight','Home'].includes(e.key))return;e.preventDefault();
    if(e.key==='Home')width=app.clientWidth*.42;
    else{var W=app.clientWidth,cur=Number(divider.getAttribute('aria-valuenow'))/W,dir=e.key==='ArrowRight'?1:-1,next=SNAPS.filter(function(r){return dir>0?r>cur+.01:r<cur-.01;});width=W*(next.length?(dir>0?next[0]:next[next.length-1]):(dir>0?SNAPS[SNAPS.length-1]:SNAPS[0]));}
    draw();save();window.dispatchEvent(new Event('resize'));});
  document.addEventListener('pb-language',draw);window.addEventListener('resize',draw);draw();
})();
