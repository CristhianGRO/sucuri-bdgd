import {downloadResult} from './api.mjs';
import {categories,category,consumerClass,symbolSVG} from './symbology.mjs';
import {validate,toKML,demoData} from './model.mjs';
import {NetworkCollection,mapFeederOf as feederOf,selectMapFeeder as selected,visibleSelection} from './networks.mjs';
import {detailData} from './lod.mjs';
import {filterLegend} from './legend_filter.mjs';
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
const enabledCategories=new Set(Object.keys(categories));
let demoActive=false, redrawTimer;
map.on('moveend',()=>{if(!layer)return;clearTimeout(redrawTimer);redrawTimer=setTimeout(()=>draw(),80);});
function attributes(f){
  const container=document.createElement('div'),heading=document.createElement('strong');
  heading.textContent=categories[category(f)].label;container.append(heading);
  const dl=document.createElement('dl');
  const visual=['consumer_summary','consumer_count','consumer_classes','consumers','consumer_list_truncated','installed_load_kw','energy_monthly_kwh','energy_annual_kwh','dic_monthly_mean','fic_monthly_mean','typical_profiles'];
  for(const k of [...new Set(['COD_ID','PAC','CTMT','tipo_no','tipo','CLAS_SUB','FAS_CON',...Object.keys(f.properties)])].filter(k=>k in f.properties&&!visual.includes(k))){const v=f.properties[k],dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=typeof v==='object'?JSON.stringify(v):String(v);dl.append(dt,dd);}
  container.append(dl);
  if(f.properties.consumer_summary)container.append(consumerPanel(f.properties.consumer_summary,'Consumidores atendidos pelo transformador'));
  if(f.properties.consumer_count)container.append(consumerPanel(f.properties,'Consumidores ligados nesta barra',true));
  return container;
}
function consumerColor(name){return categories[consumerClass({CLAS_SUB:name})].color;}
const months=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
function numeric(value){return Number(value)||0;}
function energyChart(values){
  const chart=document.createElement('section');chart.className='consumer-chart';
  const title=document.createElement('span');title.textContent='Energia consumida por mês (kWh)';chart.append(title);
  const max=Math.max(...values.map(numeric),1),width=300,height=112,barWidth=19;
  const bars=values.map((value,index)=>{const amount=numeric(value),barHeight=Math.max(1,amount/max*72),x=8+index*24,y=82-barHeight;return `<g><title>${months[index]}: ${amount.toLocaleString('pt-BR',{maximumFractionDigits:1})} kWh</title><rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="2"/><text x="${x+barWidth/2}" y="98" text-anchor="middle">${months[index][0]}</text></g>`;}).join('');
  chart.insertAdjacentHTML('beforeend',`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Energia mensal: passe o cursor sobre uma coluna para ver o valor"><path class="chart-axis" d="M6 82H298"/>${bars}</svg>`);
  return chart;
}
function profileChart(profiles){
  const chart=document.createElement('section');chart.className='consumer-chart consumer-profile';
  const title=document.createElement('span');title.textContent='Perfil típico de carga (percentual do pico)';chart.append(title);
  const choices=document.createElement('div');choices.className='profile-days';chart.append(choices);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 300 112');svg.setAttribute('role','img');chart.append(svg);
  const render=profile=>{const values=profile.points??[],points=values.map((value,index)=>`${8+index/Math.max(values.length-1,1)*284},${82-numeric(value)/100*72}`).join(' ');svg.innerHTML=`<path class="chart-axis" d="M6 82H298"/><polyline class="profile-line" points="${points}"/><text x="8" y="102">00h</text><text x="143" y="102">12h</text><text x="275" y="102">24h</text><title>${profile.day}: ${profile.profiles??0} curva(s) CRVCRG combinada(s)</title>`;};
  profiles.forEach((profile,index)=>{const button=document.createElement('button');button.type='button';button.textContent=profile.day;button.className=index?'':'active';button.onclick=()=>{for(const item of choices.children)item.classList.remove('active');button.classList.add('active');render(profile);};choices.append(button);});
  render(profiles[0]);return chart;
}
function consumerPanel(payload,title,showList=false){
  const box=document.createElement('section');box.className='consumer-panel';
  const heading=document.createElement('strong');heading.textContent=title;box.append(heading);
  const classes=Object.entries(payload.consumer_classes??{}).filter(([,count])=>Number(count)>0);
  const total=Number(payload.consumer_count??classes.reduce((sum,[,count])=>sum+Number(count),0));
  if(classes.length){let progress=0;const slices=classes.map(([name,count])=>{const start=progress;progress+=Number(count)/total*100;return `${consumerColor(name)} ${start}% ${progress}%`;});const row=document.createElement('div');row.className='consumer-breakdown';const pie=document.createElement('span');pie.className='consumer-pie';pie.style.background=`conic-gradient(${slices.join(',')})`;pie.setAttribute('aria-label',`${total} consumidores`);const legend=document.createElement('ul');for(const [name,count] of classes){const item=document.createElement('li'),swatch=document.createElement('i');swatch.style.backgroundColor=consumerColor(name);item.append(swatch,document.createTextNode(`${name}: ${count}`));legend.append(item);}row.append(pie,legend);box.append(row);}
  else {const empty=document.createElement('p');empty.textContent='Nenhum consumidor classificado.';box.append(empty);}
  const indicators=[];
  if(payload.installed_load_kw!=null)indicators.push(`Carga instalada: ${numeric(payload.installed_load_kw).toLocaleString('pt-BR',{maximumFractionDigits:2})} kW`);
  if(payload.energy_annual_kwh!=null)indicators.push(`Energia anual: ${numeric(payload.energy_annual_kwh).toLocaleString('pt-BR',{maximumFractionDigits:1})} kWh`);
  if(payload.dic_monthly_mean!=null)indicators.push(`DIC médio mensal: ${numeric(payload.dic_monthly_mean).toLocaleString('pt-BR',{maximumFractionDigits:2})} h`);
  if(payload.fic_monthly_mean!=null)indicators.push(`FIC médio mensal: ${numeric(payload.fic_monthly_mean).toLocaleString('pt-BR',{maximumFractionDigits:2})}`);
  if(indicators.length){const metrics=document.createElement('div');metrics.className='consumer-metrics';for(const item of indicators){const metric=document.createElement('span');metric.textContent=item;metrics.append(metric);}box.append(metrics);}
  if(Array.isArray(payload.energy_monthly_kwh)&&payload.energy_monthly_kwh.some(numeric))box.append(energyChart(payload.energy_monthly_kwh));
  if(Array.isArray(payload.typical_profiles)&&payload.typical_profiles.length)box.append(profileChart(payload.typical_profiles));
  if(showList){const list=document.createElement('ul');list.className='consumer-tree';for(const consumer of (payload.consumers??[]).slice(0,30)){const item=document.createElement('li');item.textContent=`${consumer.id} · ${consumer.class}`;list.append(item);}if(payload.consumer_list_truncated){const item=document.createElement('li');item.textContent='… demais consumidores disponíveis no processamento';list.append(item);}box.append(list);}
  return box;
}
function style(f){const active=!$('feeder').value || feederOf(f)===$('feeder').value;return {color:categories[category(f)].color,weight:f.geometry.type==='Point'?1:(active?2:1),opacity:active?1:.16,fillOpacity:active?.85:.16,radius:map.getZoom()>=16?5:3.5};}
function consumerAnchorIcon(f){
  const consumers=(f.properties.consumers??[]).slice(0,24),count=Number(f.properties.consumer_count??consumers.length),dots=consumers.map((consumer,index)=>{const angle=Math.round(index/Math.max(consumers.length,1)*360),radius=24+(index%3)*7;return `<i class="consumer-dot" style="--consumer-angle:${angle}deg;--consumer-radius:${radius}px;background:${consumerColor(consumer.class)}"></i>`;}).join('');
  return L.divIcon({className:'consumer-anchor-marker',html:`<div class="consumer-anchor is-pinned" aria-label="${count} consumidores conectados"><span class="consumer-hand">${dots}</span><span class="consumer-badge">${count}</span></div>`,iconSize:[116,116],iconAnchor:[58,58]});
}
function consumerClusterIcon(f){
  const count=Number(f.properties.consumer_count??0),classes=Object.entries(f.properties.consumer_classes??{}),total=Math.max(count,1);let progress=0;
  const slices=classes.map(([name,value])=>{const start=progress;progress+=Number(value)/total*100;return `${consumerColor(name)} ${start}% ${progress}%`;});
  const background=slices.length?`conic-gradient(${slices.join(',')})`:'#d7dde2';
  return L.divIcon({className:'consumer-cluster-marker',html:`<div class="consumer-cluster is-pinned" aria-label="${count} consumidores na região" style="--consumer-cluster:${background}"><span>${count}</span></div>`,iconSize:[46,46],iconAnchor:[23,23]});
}
function pointLayer(f,ll){
  const key=category(f);
  if(String(f.properties.tipo||'').toUpperCase()==='CONSUMERCLUSTER')return L.marker(ll,{icon:consumerClusterIcon(f),opacity:!$('feeder').value||feederOf(f)===$('feeder').value?1:.16,title:`${f.properties.consumer_count} consumidores nesta região`,riseOnHover:true,riseOffset:1100});
  if(key==='consumers')return L.marker(ll,{icon:consumerAnchorIcon(f),opacity:!$('feeder').value||feederOf(f)===$('feeder').value?1:.16,title:`${f.properties.consumer_count} consumidores conectados`,riseOnHover:true,riseOffset:1100});
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
    const row=document.createElement('button');row.type='button';row.className='legend-row';
    const icon=document.createElement('span');icon.innerHTML=symbolSVG(key);
    const label=document.createElement('span');label.textContent=value.label;
    row.append(icon,label);row.title=`Clique para ${enabledCategories.has(key)?'ocultar':'mostrar'} ${value.label}`;
    row.setAttribute('aria-pressed',String(enabledCategories.has(key)));
    if(!enabledCategories.has(key))row.classList.add('is-hidden');
    row.onclick=()=>{if(enabledCategories.has(key))enabledCategories.delete(key);else enabledCategories.add(key);draw();};
    box.append(row);
  }
  L.DomEvent.disableClickPropagation(box);L.DomEvent.disableScrollPropagation(box);return box;
};legend.addTo(map);
function draw(fit=false){
  if(layer) map.removeLayer(layer);
  const id=$('feeder').value;
  const visible=id&&$('isolate').checked?selected(data,id):data;
  const filtered=filterLegend(visible,enabledCategories);
  const bounds=map.getBounds().pad(.18),renderable=detailData(filtered,map.getZoom(),{west:bounds.getWest(),east:bounds.getEast(),south:bounds.getSouth(),north:bounds.getNorth()});
  layer=L.geoJSON(renderable,{style,pointToLayer:pointLayer,onEachFeature:(f,l)=>{
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
