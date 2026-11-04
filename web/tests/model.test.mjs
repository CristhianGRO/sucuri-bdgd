import test from 'node:test';
import assert from 'node:assert/strict';
import {validate,selected,toKML,demoData} from '../model.mjs';
test('seleção exporta somente o alimentador solicitado',()=>{
 const data=validate(demoData()); const result=selected(data,'DEMO-02');
 assert.equal(result.features.length,28);
 assert.ok(result.features.every(f=>f.properties.CTMT==='DEMO-02'));
 assert.equal(selected(data,'inexistente').features.length,0);
 assert.equal(data.features.length,84);
});
test('rejeita coordenadas projetadas e elementos sem alimentador',()=>{
 const data=demoData(); data.features[0].geometry.coordinates[0]=[300000,7400000];
 assert.throws(()=>validate(data),/WGS84/);
 const other=demoData();delete other.features[0].properties.CTMT;
 assert.throws(()=>validate(other),/CTMT/);
 assert.throws(()=>validate({type:'FeatureCollection',features:[]}),/vazio/);
});
test('KML preserva multilinhas e escapa atributos',()=>{
 const data={type:'FeatureCollection',features:[{type:'Feature',properties:{CTMT:'A',COD_ID:'<script>&"'},geometry:{type:'MultiLineString',coordinates:[[[0,0],[1,1]],[[2,2],[3,3]]]}}]};
 const xml=toKML(validate(data));
 assert.match(xml,/<MultiGeometry>/);assert.equal((xml.match(/<LineString>/g)||[]).length,2);
 assert.ok(!xml.includes('<script>'));assert.match(xml,/&lt;script&gt;&amp;&quot;/);
});
