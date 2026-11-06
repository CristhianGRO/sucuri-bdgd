import {downloadResult} from './api.mjs';
import {categories,category,symbolSVG} from './symbology.mjs';
import {validate,toKML,demoData} from './model.mjs';
import {NetworkCollection,mapFeederOf as feederOf,selectMapFeeder as selected,visibleSelection} from './networks.mjs';
const $=id=>document.getElementById(id);
function status(message){$('status').textContent=message;}
if(!window.L){status('Não foi possível carregar o mapa. Verifique a conexão e recarregue a página.');throw Error('Leaflet unavailable');}
const map=L.map('map',{preferCanvas:true,renderer:L.canvas({tolerance:7})}).setView([-22.91,-47.07],13);
const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · <a href="https://www.openstreetmap.org/fixthemap">Corrigir mapa</a>',maxZoom:19}).addTo(map).on('tileerror',()=>status('Fundo indisponível. Os elementos da rede continuam acessíveis.'));
$('basemap').onchange=()=>{const mode=$('basemap').value;$('map').classList.toggle('light-map',mode==='light');if(mode==='none')map.removeLayer(tiles);else if(!map.hasLayer(tiles))tiles.addTo(map);};
window.addEventListener('sucuri-network',event=>{try{load(event.detail.data,event.detail.label,{dataset:event.detail.dataset,add:event.detail.add,download:event.detail.download});}catch(error){status(error.message);}});
L.control.scale({imperial:false}).addTo(map);
let data, layer;
const networks=new NetworkCollection();
let demoActive=false;
map.on('zoomend',()=>{if(layer)layer.setStyle(style);});
function attributes(f){
  const container=document.createElement('div'),heading=document.createElement('strong');
  heading.textContent=categories[category(f)].label;container.append(heading);
  const dl=document.createElement('dl');
  for(const k of [...new Set(['COD_ID','CTMT','tipo_no','tipo','CLAS_SUB','FAS_CON',...Object.keys(f.properties)])].filter(k=>k in f.properties)){const v=f.properties[k],dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=typeof v==='object'?JSON.stringify(v):String(v);dl.append(dt,dd);}
  container.append(dl);return container;
}
function style(f){const active=!$('feeder').value || feederOf(f)===$('feeder').value;return {color:categories[category(f)].color,weight:f.geometry.type==='Point'?1:(active?2:1),opacity:active?1:.16,fillOpacity:active?.85:.16,radius:map.getZoom()>=16?5:3.5};}
function pointLayer(f,ll){
  const key=category(f);
  if(['res','com','ind','load','transformer','substation'].includes(key)){
    return L.marker(ll,{icon:L.divIcon({className:`network-symbol symbol-${key}`,html:symbolSVG(key),iconSize:key==='substation'?[60,48]:[40,40],iconAnchor:key==='substation'?[30,24]:[20,20]}),opacity:!$('feeder').value||feederOf(f)===$('feeder').value?1:.16,title:categories[key].label,riseOnHover:true,riseOffset:1000,zIndexOffset:key==='substation'?2000:key==='transformer'?500:300});
  }
  return L.circleMarker(ll,style(f));
}
const legend=L.control({position:'topright'});
legend.onAdd=()=>{
  const box=L.DomUtil.create('details','network-legend');box.open=!window.matchMedia('(max-width:760px)').matches;
  const title=document.createElement('summary');title.textContent='Legenda';box.append(title);
  for(const [key,value] of Object.entries(categories)){
    const row=document.createElement('div');row.className='legend-row';
    const icon=document.createElement('span');icon.innerHTML=symbolSVG(key);
    const label=document.createElement('span');label.textContent=value.label;
    row.append(icon,label);box.append(row);
  }
  L.DomEvent.disableClickPropagation(box);L.DomEvent.disableScrollPropagation(box);return box;
};legend.addTo(map);
function draw(fit=false){
  if(layer) map.removeLayer(layer);
  const id=$('feeder').value;
  const visible=id&&$('isolate').checked?selected(data,id):data;
  layer=L.geoJSON(visible,{style,pointToLayer:pointLayer,onEachFeature:(f,l)=>{
    const info=attributes(f),hint=document.createElement('p');
    hint.className='tooltip-hint';hint.textContent='Clique para fixar os detalhes no painel.';info.insertBefore(hint,info.children[1]);
    l.bindTooltip(info,{sticky:true,direction:'auto',offset:[18,-18],className:'network-tooltip',opacity:1});
    const highlight=()=>{
      if(l instanceof L.Marker){l.getElement()?.classList.add('is-hovered');l.setOpacity(1);}
      else {l.setStyle({...style(f),weight:f.geometry.type==='Point'?2:6,opacity:1,fillOpacity:1});if(l.setRadius)l.setRadius(7);}
    };
    const restore=()=>{
      if(l instanceof L.Marker){l.getElement()?.classList.remove('is-hovered');l.setOpacity(!$('feeder').value||feederOf(f)===$('feeder').value?1:.16);}
      else {l.setStyle(style(f));if(l.setRadius)l.setRadius(style(f).radius);}
    };
    l.on('mouseover',highlight);l.on('mouseout',restore);
    if(l instanceof L.Marker)l.on('add',()=>{
      const element=l.getElement();
      element.addEventListener('focus',()=>{highlight();l.openTooltip();});
      element.addEventListener('blur',()=>{restore();l.closeTooltip();});
    });
    l.on('click',()=>{$('feeder').value=feederOf(f);$('details').replaceChildren(attributes(f));draw();});
  }}).addTo(map);
  $('count').textContent=visible.features.length.toLocaleString('pt-BR');
  $('geojson').disabled=$('kmz').disabled=!id;
  if(fit) zoom();
}
function zoom(){const id=$('feeder').value;const bounds=L.geoJSON(id?selected(data,id):data).getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[35,35],maxZoom:17});}
function refreshNetworks(fit=true){
  const previous=$('feeder').value;
  data=networks.visibleData();
  const visible=[...networks.items.values()].filter(item=>item.visible);
  $('feeder').replaceChildren(new Option('Todos os alimentadores',''),...visible.map(item=>new Option(`${item.dataset} / ${item.feeder}`,item.key)));
  $('feeder').value=visibleSelection(visible,previous);
  $('feeders').textContent=visible.length;
  $('source').textContent=visible.length===1?visible[0].label:`${visible.length} alimentadores visíveis · ${networks.items.size} carregados`;
  $('network-list').replaceChildren();
  for(const item of networks.items.values()){
    const row=document.createElement('div');row.className='network-row';
    const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=item.visible;
    const name=document.createElement('span');name.textContent=`${item.dataset} / ${item.feeder}`;
    check.onchange=()=>{networks.setVisible(item.key,check.checked);refreshNetworks(false);};label.append(check,name);row.append(label);
    if(item.download){const link=document.createElement('a');link.href='#';link.onclick=e=>{e.preventDefault();downloadResult(item.download,`${item.feeder}-powerflow.zip`).catch(e=>status(e.message));};link.textContent='Fluxo ↓';link.title=`Exportar ${item.dataset} / ${item.feeder}`;row.append(link);}
    const remove=document.createElement('button');remove.textContent='×';remove.title=`Remover ${item.dataset} / ${item.feeder}`;remove.setAttribute('aria-label',remove.title);remove.onclick=()=>{networks.remove(item.key);$('details').textContent='Clique na rede para inspecionar.';refreshNetworks();};row.append(remove);$('network-list').append(row);
  }
  draw(fit);
}
function load(next,label,{dataset='Arquivo',add=false,download=null,demo=false}={}){
  networks.add(next,dataset,label,download,!add||demoActive);
  demoActive=demo;
  $('feeder').value='';
  $('details').textContent='Clique em um elemento para inspecionar seus atributos.';
  refreshNetworks();
  status('Rede carregada. Use a lista para mostrar, ocultar ou remover alimentadores.');
}
$('feeder').onchange=()=>{$('details').textContent='Clique em um elemento para inspecionar seus atributos.';draw(true);};
$('isolate').onchange=()=>draw();$('fit').onclick=zoom;
$('clear').onclick=()=>{$('feeder').value='';$('details').textContent='Seleção limpa.';draw();};
$('demo').onclick=()=>load(demoData(),'DEMONSTRAÇÃO · Rede fictícia em Campinas',{dataset:'Demonstração',demo:true});
$('file').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>25*1024*1024)throw Error('Arquivo maior que 25 MB. Exporte um recorte menor.');load(JSON.parse(await file.text()),`ARQUIVO LOCAL · ${file.name}`,{dataset:file.name,add:$('append-map').checked});}catch(e){status(`Falha ao abrir: ${e.message}`);}finally{event.target.value='';}};
function download(blob,extension,id){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${(networks.items.get(id)?.feeder??id).replace(/[^a-zA-Z0-9_-]/g,'_')}.${extension}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
$('geojson').onclick=()=>{const id=$('feeder').value;if(id)download(new Blob([JSON.stringify(selected(data,id),null,2)],{type:'application/geo+json'}),'geojson',id);};
$('kmz').onclick=async()=>{const id=$('feeder').value;if(!id)return;try{if(!window.JSZip)throw Error('Biblioteca de compactação indisponível. Verifique a conexão.');const zip=new JSZip();zip.file('doc.kml',toKML(selected(data,id)));download(await zip.generateAsync({type:'blob',compression:'DEFLATE',mimeType:'application/vnd.google-earth.kmz'}),'kmz',id);status(`KMZ de ${id} exportado.`);}catch(e){status(e.message);}};
load(demoData(),'DEMONSTRAÇÃO · Rede fictícia em Campinas',{dataset:'Demonstração',demo:true});
