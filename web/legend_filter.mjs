import {category,consumerClass} from './symbology.mjs';

function filteredConsumers(payload, enabled){
  if(!payload)return payload;
  const classes={};
  for(const [name,count] of Object.entries(payload.consumer_classes??{})){
    if(enabled.has(consumerClass({CLAS_SUB:name})))classes[name]=Number(count);
  }
  const consumers=(payload.consumers??[]).filter(consumer=>enabled.has(consumerClass({CLAS_SUB:consumer.class})));
  return {...payload,consumer_classes:classes,consumer_count:Object.values(classes).reduce((sum,count)=>sum+count,0),consumers};
}

export function filterLegend(data, enabled){
  const features=[];
  for(const feature of data.features){
    const key=category(feature),props=feature.properties??{};
    if(!enabled.has(key))continue;
    const next={...props};
    if(next.consumer_summary)next.consumer_summary=filteredConsumers(next.consumer_summary,enabled);
    if(next.consumer_count!=null){
      Object.assign(next,filteredConsumers(next,enabled));
      // Uma flor/agrupamento sem classe selecionada não é desenhado.
      if(key==='consumers'&&!next.consumer_count)continue;
    }
    features.push({...feature,properties:next});
  }
  return {type:'FeatureCollection',features};
}
