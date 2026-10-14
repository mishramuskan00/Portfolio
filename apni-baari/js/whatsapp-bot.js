(function(){
  // Remove accidental visible HTML-tag text if a browser exposes a stray head marker.
  document.addEventListener('DOMContentLoaded',()=>{
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    const remove=[];
    while(walker.nextNode()){
      const n=walker.currentNode;
      const v=n.nodeValue.trim().toLowerCase();
      if(v==='head' || v==='<head>' || v==='</head>') remove.push(n);
    }
    remove.forEach(n=>n.parentNode&&n.parentNode.removeChild(n));
  });
  const replies={
    status:'आपका टोकन AB-2026-1048 अभी लाइव कतार में है। अनुमानित प्रतीक्षा 42 मिनट है।',
    booking:'टोकन बुक करने के लिए नीचे दिए विकल्प में “टोकन बुक करें” चुनें। हम आपको ई-उपार्जन बुकिंग पेज पर ले जा रहे हैं।',
    msp:'आज की MSP: गेहूँ ₹2,425 • धान ₹2,320 • सरसों ₹5,950 • चना ₹5,650 प्रति क्विंटल।',
    weather:'Karnal में बारिश की संभावना 45% है। 40% से अधिक होने पर Covered Shed routing और penalty-free rescheduling उपलब्ध है।',
    payment:'भुगतान स्थिति: Bank Credit Initiated. PFMS UTR: PFMSAB202609061248.',
    help:'मैं केवल बटन से सहायता देता हूँ। ऊपर दिए विकल्प चुनें: टोकन स्थिति, टोकन बुकिंग, MSP, मौसम, भुगतान या सहायता।'
  };
  function el(id){return document.getElementById(id)}
  function addBot(text){
    const body=el('waBody'); if(!body)return;
    const b=document.createElement('div'); b.className='wa-bubble bot'; b.textContent=text; body.appendChild(b); body.scrollTop=body.scrollHeight;
  }
  function choose(key){
    const body=el('waBody'); if(!body)return;
    const label={status:'टोकन स्थिति',booking:'टोकन बुक करें',msp:'आज की MSP',weather:'मौसम अलर्ट',payment:'भुगतान स्थिति',help:'मदद / Help'}[key]||'सहायता';
    const u=document.createElement('div'); u.className='wa-bubble user'; u.textContent=label; body.appendChild(u); body.scrollTop=body.scrollHeight;
    setTimeout(()=>{addBot(replies[key]||replies.help); if(key==='booking'){setTimeout(()=>{const a=document.createElement('button');a.className='wa-action-link';a.textContent='ई-उपार्जन बुकिंग खोलें';a.onclick=()=>location.href='procurement.html#booking';body.appendChild(a);body.scrollTop=body.scrollHeight;},250)}},300);
  }
  function openBot(){el('waWindow').classList.add('open');el('waFab').setAttribute('aria-expanded','true');}
  function closeBot(){el('waWindow').classList.remove('open');el('waFab').setAttribute('aria-expanded','false');}
  window.chooseWhatsApp=choose;
  window.toggleWhatsApp=function(){el('waWindow').classList.contains('open')?closeBot():openBot()};
  document.addEventListener('DOMContentLoaded',()=>{
    const fab=el('waFab'); if(fab)fab.addEventListener('click',window.toggleWhatsApp);
    const close=el('waClose'); if(close)close.addEventListener('click',closeBot);
    const help=el('waHelp'); if(help)help.addEventListener('click',()=>choose('help'));
    // This floating widget is a scripted preview only (fixed replies, no
    // server round-trip). The real, backend-connected WhatsApp bot lives at
    // whatsapp-simulator.html — link to it so it's not mistaken for the
    // functional one.
    const opts=document.querySelector('.wa-options');
    if(opts && !document.getElementById('waRealBotLink')){
      const link=document.createElement('a');
      link.id='waRealBotLink';
      link.className='wa-option';
      link.href='whatsapp-simulator.html';
      link.style.textDecoration='none';
      link.style.display='block';
      link.style.textAlign='center';
      link.textContent='🤖 Try the real WhatsApp bot (live demo)';
      opts.appendChild(link);
    }
  });
})();
