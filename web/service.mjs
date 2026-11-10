import {api,pair,downloadResult,isLocal} from './api.mjs';
const $=id=>document.getElementById(id);
let basesPath='', next=-1, query='', active=false, catalogItems=[],cacheCheck=0;
async function checkCache(){
 const token=++cacheCheck;const dataset=$('dataset').value,feeder=$('source-feeder').value;
 $('cache-note').textContent='';if(!dataset||!feeder)return;
 try{const result=await api(`/api/cache?${new URLSearchParams({dataset,feeder,crs:$('crs').value})}`);if(token!==cacheCheck)return;
 $('cache-note').textContent=result.available?($('force-process').checked?'Resultado salvo disponível, mas será recalculado por sua escolha.':'Resultado salvo disponível. Será carregado sem recalcular.'):'Sem resultado compatível salvo. O primeiro acesso precisa processar.';
 }catch(e){if(token===cacheCheck)$('cache-note').textContent=e.message;}
}
$('force-process').onchange=checkCache;$('source-feeder').onchange=checkCache;$('crs').onchange=checkCache;
const note=message=>{$('api-note').textContent=message;};
async function datasets(preferred){const items=await api('/api/datasets');if(!items.length)note(`Nenhuma base encontrada em ${basesPath}. Baixe uma em “Obter base da ANEEL” ou copie as pastas das bases antigas (com CTMT.csv) para esse diretório e atualize a página.`);$('dataset').replaceChildren(new Option('Selecione uma base',''),...items.map(i=>new Option(i.title,i.id)));if(preferred)$('dataset').value=preferred;await feeders();}
async function feeders(){const id=$('dataset').value;$('source-feeder').replaceChildren();if(!id){cacheCheck++;$('cache-note').textContent='';return;}const items=await api(`/api/feeders?dataset=${encodeURIComponent(id)}`);if($('dataset').value!==id)return;$('source-feeder').replaceChildren(...items.map(i=>new Option(`${i.id} · ${i.name}`,i.id)));if(id.startsWith('ANEEL_'))$('crs').value='EPSG:4326';await checkCache();}
$('dataset').onchange=()=>feeders().catch(e=>note(e.message));
async function watch(id,{cached=false,add=true}={}){
 $('job-panel').hidden=false;$('job-panel').open=true;
 for(;;){const job=await api(`/api/jobs/${id}`);$('job-log').textContent=job.log||'Aguardando execução…';$('job-log').scrollTop=$('job-log').scrollHeight;note(job.status==='queued'?'Na fila de processamento…':'Processamento em andamento…');
  if(job.status==='failed')throw Error(job.error);
  if(job.status==='completed'){
   if(job.kind==='import'){await datasets(job.result.dataset);note('Base importada. Selecione o alimentador e forme a rede.');}
   else {const result=job.result;$('powerflow').href='#';$('powerflow').onclick=e=>{e.preventDefault();downloadResult(`/api/jobs/${id}/powerflow.zip`,`${result.feeder}-powerflow.zip`).catch(e=>note(e.message));};$('powerflow').download=`${result.feeder}-powerflow.zip`;$('powerflow').textContent=`Fluxo · ${result.feeder} ↓`;$('powerflow').hidden=false;$('result-note').textContent=`${result.nodes} nós · ${result.edges} ligações · ${result.nodes_without_coordinates} nós sem coordenadas. Arquivos de entrada; simulação não executada.`;
    const data=await api(`/api/jobs/${id}/network.geojson`);window.dispatchEvent(new CustomEvent('sucuri-network',{detail:{data,label:`${result.dataset} / ${result.feeder} · ${result.geometry}`,dataset:result.dataset,add,download:`/api/jobs/${id}/powerflow.zip`,powerflow:result.powerflow}}));note(cached?'Resultado salvo carregado, sem reprocessar.':'Rede processada e salva para reutilização.');await checkCache();}
   return;
  }
  await new Promise(resolve=>setTimeout(resolve,1500));
 }
}
async function submit(kind,args){if(active)return;active=true;const add=$('append-map').checked;$('process').disabled=$('import').disabled=true;try{const job=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,args})});await watch(job.id,{cached:job.cached,add});}catch(e){note(`Falha: ${e.message}`);}finally{active=false;$('process').disabled=false;$('import').disabled=!$('catalog-results').value;}}
$('process').onclick=()=>{if(!$('dataset').value||!$('source-feeder').value){note('Selecione uma base e um alimentador.');return;}$('powerflow').hidden=true;$('result-note').textContent='';submit('process',{dataset:$('dataset').value,feeder:$('source-feeder').value,crs:$('crs').value,force:$('force-process').checked});};
window.addEventListener('sucuri-run-powerflow',async event=>{if(active)return;const {dataset,feeder}=event.detail??{};try{$('dataset').value=dataset;await feeders();$('source-feeder').value=feeder;$('force-process').checked=false;$('powerflow').hidden=true;$('result-note').textContent='';submit('process',{dataset,feeder,crs:$('crs').value,force:false,run_powerflow:true});}catch(error){note(error.message);}});
async function search(start=1){$('search').disabled=true;try{const result=await api(`/api/catalog?q=${encodeURIComponent(query)}&start=${start}`);catalogItems=result.items;$('catalog-results').replaceChildren(...result.items.map(i=>new Option(i.title,i.id)));next=result.next;$('next').disabled=next<0;$('import').disabled=active||!result.items.length;showSize();$('catalog-info').textContent+=` · ${result.total} bases encontradas`;}catch(e){$('catalog-info').textContent=e.message;}finally{$('search').disabled=false;}}
function showSize(){const item=catalogItems.find(i=>i.id===$('catalog-results').value);$('catalog-info').textContent=item?`Download: ${item.size > 0 ? (item.size/1024**2).toLocaleString('pt-BR',{maximumFractionDigits:0}) + ' MB' : 'tamanho não informado pela ANEEL'}. A importação pode levar vários minutos.`:'Nenhuma base encontrada.';}
$('catalog-results').onchange=showSize;
$('search').onclick=()=>{query=$('catalog-query').value;search();};$('next').onclick=()=>search(next);
$('catalog-query').onkeydown=e=>{if(e.key==='Enter')$('search').click();};
$('import').onclick=()=>{const id=$('catalog-results').value;if(id)submit('import',{item_id:id});};
async function connect(){
 const health=await api('/api/health');basesPath=health.storage.bases;
 $('connection').textContent='Python conectado';$('processing').disabled=health.process_available===false;$('remote').disabled=!health.import_available;
 $('local-status').textContent=`Dados neste computador: ${health.storage.bases}`;
 $('setup').open=false;
 note(health.process_available===false?'Dependências ausentes. Reinstale o SUCURI Local.':'Motor local conectado. Escolha uma base ou baixe uma da ANEEL.');await datasets();
}
$('connect-local').onclick=async()=>{
 $('connect-local').disabled=true;$('local-status').textContent='Conectando…';
 try{await pair($('pair-code').value.trim());await connect();$('pair-code').value='';}
 catch(e){$('local-status').textContent=e.message;}
 finally{$('connect-local').disabled=false;}
};
if(isLocal||sessionStorage.getItem('sucuri-token')){try{await connect();}catch(e){$('local-status').textContent=e.message;$('setup').open=true;note('Conecte o aplicativo local para processar. O mapa continua disponível.');}}
else note('Conecte o SUCURI Local para baixar e processar bases no seu computador.');
