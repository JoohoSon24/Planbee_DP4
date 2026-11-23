/* Resizable, keyboard-accessible conversation / board split. Local preferences only. */
(function(){
  'use strict';
  var app=document.querySelector('.app'),chat=document.querySelector('.chan'),board=document.querySelector('.board');if(!app||!chat||!board)return;
  var divider=document.createElement('div');divider.className='panel-divider';divider.tabIndex=0;divider.setAttribute('role','separator');divider.setAttribute('aria-orientation','vertical');
  chat.id='chat-panel';divider.setAttribute('aria-controls','chat-panel');chat.after(divider);app.classList.add('resizable-panels');
  var toggle=document.createElement('button');toggle.type='button';toggle.className='btn sm chat-toggle';toggle.setAttribute('aria-controls','chat-panel');board.querySelector('.pane-h').append(toggle);
  var width=null,collapsed=false;try{width=Number(localStorage.getItem('pb-chat-width'))||null;collapsed=localStorage.getItem('pb-chat-collapsed')==='true';}catch(err){}
  function en(){return document.documentElement.getAttribute('data-lang')==='en';}
  function bounds(){return {min:320,max:Math.max(320,app.clientWidth-332)};}
  function save(){try{localStorage.setItem('pb-chat-width',String(width));localStorage.setItem('pb-chat-collapsed',String(collapsed));}catch(err){}}
  function draw(){
    var b=bounds();if(width===null&&window.innerWidth>900)width=app.clientWidth*.42;var actual=Math.round(Math.max(b.min,Math.min(b.max,width||app.clientWidth*.42)));
    app.style.setProperty('--chat-width',actual+'px');app.classList.toggle('chat-collapsed',collapsed);
    divider.setAttribute('aria-valuemin',b.min);divider.setAttribute('aria-valuemax',b.max);divider.setAttribute('aria-valuenow',actual);
    divider.setAttribute('aria-label',en()?'Resize chat and board. Arrow keys adjust; Home resets.':'채팅·보드 너비 조절. 방향키로 조절, Home으로 초기화');
    toggle.textContent=collapsed?(en()?'Open chat':'채팅 열기'):(en()?'Hide chat':'채팅 접기');toggle.setAttribute('aria-expanded',String(!collapsed));
  }
  toggle.onclick=function(){collapsed=!collapsed;draw();save();window.dispatchEvent(new Event('resize'));if(!collapsed)document.getElementById('change-input').focus();};
  divider.addEventListener('pointerdown',function(e){if(e.button!==0||window.innerWidth<=900)return;e.preventDefault();divider.setPointerCapture(e.pointerId);app.classList.add('panel-resizing');});
  divider.addEventListener('pointermove',function(e){if(!divider.hasPointerCapture(e.pointerId))return;width=e.clientX-app.getBoundingClientRect().left;draw();});
  function finish(e){if(divider.hasPointerCapture(e.pointerId))divider.releasePointerCapture(e.pointerId);app.classList.remove('panel-resizing');save();window.dispatchEvent(new Event('resize'));}
  divider.addEventListener('pointerup',finish);divider.addEventListener('pointercancel',finish);
  divider.addEventListener('lostpointercapture',function(){app.classList.remove('panel-resizing');});
  divider.addEventListener('dblclick',function(){width=app.clientWidth*.42;draw();save();});
  divider.addEventListener('keydown',function(e){if(!['ArrowLeft','ArrowRight','Home'].includes(e.key))return;e.preventDefault();width=e.key==='Home'?app.clientWidth*.42:Number(divider.getAttribute('aria-valuenow'))+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?50:16);draw();save();});
  document.addEventListener('pb-language',draw);window.addEventListener('resize',draw);draw();
})();
