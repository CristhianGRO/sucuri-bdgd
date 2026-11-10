import test from 'node:test';
import assert from 'node:assert/strict';
import {filterLegend} from '../legend_filter.mjs';
const feature=(tipo,props={})=>({type:'Feature',properties:{tipo,...props},geometry:{type:'Point',coordinates:[-47,-22]}});
test('filtra camadas e classes de consumidores sem alterar a barra',()=>{
 const data={type:'FeatureCollection',features:[
  feature('SSDMT'),
  feature('ConsumerAnchor',{consumer_count:3,consumer_classes:{RE1:2,CO1:1},consumers:[{id:'r',class:'RE1'},{id:'c',class:'CO1'}]}),
  feature('PAC_LV',{consumer_count:3,consumer_classes:{RE1:2,CO1:1}})
 ]};
 const enabled=new Set(['mt','bt','consumers','res']);
 const result=filterLegend(data,enabled);
 assert.equal(result.features.length,3);
 const anchor=result.features.find(item=>item.properties.tipo==='ConsumerAnchor').properties;
 assert.equal(anchor.consumer_count,2);assert.deepEqual(anchor.consumer_classes,{RE1:2});
 assert.equal(result.features.find(item=>item.properties.tipo==='PAC_LV').properties.consumer_count,2);
});
test('ocultar consumidores remove as flores, mas não as linhas',()=>{
 const data={type:'FeatureCollection',features:[feature('SSDMT'),feature('ConsumerAnchor',{consumer_count:1,consumer_classes:{RE1:1}})]};
 const result=filterLegend(data,new Set(['mt','res']));
 assert.equal(result.features.length,1);assert.equal(result.features[0].properties.tipo,'SSDMT');
});
