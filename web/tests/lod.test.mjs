import test from 'node:test';
import assert from 'node:assert/strict';
import {consumerClusters,detailData} from '../lod.mjs';
const anchor=(longitude,latitude,count,classes)=>({type:'Feature',properties:{tipo:'ConsumerAnchor',consumer_count:count,consumer_classes:classes},geometry:{type:'Point',coordinates:[longitude,latitude]}});
test('agrupa consumidores próximos no afastamento',()=>{
 const clusters=consumerClusters([anchor(-47,-22,3,{RE1:2,CO1:1}),anchor(-47.001,-22.001,2,{RE1:2})],12);
 assert.equal(clusters.length,1);assert.equal(clusters[0].properties.consumer_count,5);assert.deepEqual(clusters[0].properties.consumer_classes,{RE1:4,CO1:1});
});
test('oculta nós topológicos no afastamento e os expande no detalhe',()=>{
 const data={type:'FeatureCollection',features:[
  {type:'Feature',properties:{tipo_no:'Substation',map_source:'Nó topológico calculado'},geometry:{type:'Point',coordinates:[-47,-22]}},
  {type:'Feature',properties:{tipo_no:'PAC_LV',map_source:'Nó topológico calculado'},geometry:{type:'Point',coordinates:[-47.01,-22.01]}},
  anchor(-47.02,-22.02,1,{RE1:1})
 ]};
 assert.equal(detailData(data,12).features.filter(f=>f.properties.tipo_no).length,1);
 const detailed=detailData(data,16);assert.equal(detailed.features.filter(f=>f.properties.tipo_no).length,2);assert.equal(detailed.features.filter(f=>f.properties.tipo==='ConsumerAnchor').length,1);
});
