import test from 'node:test';
import assert from 'node:assert/strict';
import {NetworkCollection,mapFeederOf,selectMapFeeder,visibleSelection} from '../networks.mjs';
const fixture=(id,x=0)=>({type:'FeatureCollection',features:[{type:'Feature',properties:{CTMT:id,COD_ID:'point'},geometry:{type:'Point',coordinates:[x,0]}}]});
test('mantém alimentadores, substitui duplicados e separa bases com mesmo CTMT',()=>{
 const networks=new NetworkCollection();networks.add(fixture('A'),'BASE1','one');networks.add(fixture('B'),'BASE1','two');networks.add(fixture('A',1),'BASE2','three');
 assert.equal(networks.items.size,3);networks.add(fixture('A',2),'BASE1','updated');assert.equal(networks.items.size,3);
 const selected=selectMapFeeder(networks.visibleData(),JSON.stringify(['BASE1','A']));assert.equal(selected.features.length,1);assert.equal(selected.features[0].geometry.coordinates[0],2);assert.ok(!('_sucuri_dataset' in selected.features[0]));
 const key=mapFeederOf(networks.visibleData().features[0]);networks.setVisible(key,false);assert.equal(networks.visibleData().features.length,2);networks.setVisible(key,true);networks.remove(key);assert.equal(networks.items.size,2);
});
test('limpa a seleção quando o alimentador selecionado deixa de estar visível',()=>{
 const networks=new NetworkCollection();networks.add(fixture('A'),'BASE','one');networks.add(fixture('B'),'BASE','two');
 const [a,b]=[...networks.items.values()];assert.equal(visibleSelection([a,b],a.key),a.key);
 networks.setVisible(a.key,false);assert.equal(visibleSelection([...networks.items.values()].filter(item=>item.visible),a.key),'');
});
test('substituição explícita e carga inválida não apagam camadas válidas',()=>{
 const networks=new NetworkCollection();networks.add(fixture('A'),'BASE','one');assert.throws(()=>networks.add({features:[]},'BASE','bad'));assert.equal(networks.items.size,1);
 networks.add(fixture('B'),'BASE','two',null,true);assert.deepEqual([...networks.items.values()].map(x=>x.feeder),['B']);
});
