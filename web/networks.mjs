import {feederOf,validate} from './model.mjs';
export const mapFeederOf=f=>JSON.stringify([f._sucuri_dataset??'',feederOf(f)]);
export const selectMapFeeder=(data,key)=>({type:'FeatureCollection',features:data.features.filter(f=>mapFeederOf(f)===key).map(({_sucuri_dataset,...f})=>f)});
export const visibleSelection=(items,selectedKey)=>items.some(item=>item.key===selectedKey)?selectedKey:'';
export class NetworkCollection {
  constructor(){this.items=new Map();}
  add(data,dataset,label,download=null,replace=false){
    validate(data);
    const next=replace?new Map():new Map(this.items);
    const groups=new Map();
    for(const feature of data.features){const id=feederOf(feature);if(!groups.has(id))groups.set(id,[]);groups.get(id).push({...feature,_sucuri_dataset:dataset});}
    for(const [feeder,features] of groups){const key=JSON.stringify([dataset,feeder]);next.set(key,{key,dataset,feeder,label,download,visible:true,data:{type:'FeatureCollection',features}});}
    if([...next.values()].reduce((n,item)=>n+item.data.features.length,0)>100000)throw Error('Limite de 100 mil elementos no mapa. Remova um alimentador antes de adicionar outro.');
    this.items=next;
  }
  visibleData(){return {type:'FeatureCollection',features:[...this.items.values()].filter(x=>x.visible).flatMap(x=>x.data.features)};}
  remove(key){this.items.delete(key);}
  setVisible(key,visible){const item=this.items.get(key);if(item)item.visible=visible;}
}
