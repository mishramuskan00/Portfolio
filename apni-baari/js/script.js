
// Mobile navigation
const menuToggle = document.querySelector(".menu-toggle");
const navLinks = document.querySelector(".nav-links");
if(menuToggle){
  menuToggle.addEventListener("click", () => navLinks.classList.toggle("open"));
}

// Homepage multimedia slider
const slides = [...document.querySelectorAll(".slide")];
const dots = [...document.querySelectorAll(".dot")];
const heroVideo = document.querySelector(".hero-video");
let currentSlide = 0;
let sliderTimer;

function isVideoSlide(index){
  return !!slides[index]?.querySelector(".hero-video");
}

function stopAutoAdvance(){
  clearTimeout(sliderTimer);
  sliderTimer = null;
}

function playCurrentVideo(){
  if(!heroVideo || !isVideoSlide(currentSlide)) return;
  heroVideo.currentTime = 0;
  heroVideo.play().catch(()=>{
    // Autoplay can be blocked by the browser; the video remains available to play manually.
  });
}

function showSlide(index){
  if(!slides.length) return;
  stopAutoAdvance();

  // Pause/reset the video whenever we leave its slide.
  if(heroVideo && isVideoSlide(currentSlide)){
    heroVideo.pause();
    heroVideo.currentTime = 0;
  }

  currentSlide = (index + slides.length) % slides.length;
  slides.forEach((s,i)=>s.classList.toggle("active",i===currentSlide));
  dots.forEach((d,i)=>d.classList.toggle("active",i===currentSlide));

  // The video is intentionally allowed to finish completely before the next image appears.
  if(isVideoSlide(currentSlide)){
    playCurrentVideo();
  }else if(slides.length > 1){
    sliderTimer = setTimeout(()=>showSlide(currentSlide+1),5000);
  }
}

if(heroVideo){
  heroVideo.addEventListener("ended",()=>{
    if(isVideoSlide(currentSlide)) showSlide(currentSlide+1);
  });
}

document.querySelector(".prev")?.addEventListener("click",()=>showSlide(currentSlide-1));
document.querySelector(".next")?.addEventListener("click",()=>showSlide(currentSlide+1));
dots.forEach((dot,i)=>dot.addEventListener("click",()=>showSlide(i)));
showSlide(0);

// Search: simple client-side highlight/message for the static demo
const searchForm = document.querySelector("#siteSearch");
if(searchForm){
  searchForm.addEventListener("submit",(e)=>{
    e.preventDefault();
    const q = searchForm.querySelector("input").value.trim();
    if(!q){ alert("कृपया खोज शब्द दर्ज करें।"); return; }
    alert("डेमो खोज: " + q + "\\nइस static prototype में आप अपने वास्तविक search backend/API को बाद में जोड़ सकते हैं।");
  });
}

// Current year
document.querySelectorAll("[data-year]").forEach(el=>el.textContent=new Date().getFullYear());

// Login demo
document.querySelector("#loginForm")?.addEventListener("submit",(e)=>{
  e.preventDefault();
  const user = document.querySelector("#username").value.trim();
  if(!user){ alert("कृपया मोबाइल/यूज़र आईडी दर्ज करें।"); return; }
  alert("डेमो लॉगिन सफल। वास्तविक authentication/API बाद में जोड़ा जा सकता है।");
});
