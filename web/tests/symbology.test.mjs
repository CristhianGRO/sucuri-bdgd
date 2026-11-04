import test from 'node:test';
import assert from 'node:assert/strict';
import {category,consumerClass} from '../symbology.mjs';
import {demoData} from '../model.mjs';
test('classes BDGD, aliases e classes desconhecidas',()=>{
 for(const [raw,key] of [['RE1','res'],['RE5','res'],['RES','res'],['CO1','com'],['COM','com'],['IN6','ind'],['IND','ind'],['RU1','load'],['','load'],['INEXISTENTE','load']]) assert.equal(consumerClass({CLAS_SUB:raw}),key);
});
test('identifica os tipos do grafo e do GDB',()=>{
 for(const [type,key] of [['MV_Line','mt'],['SSDMT','mt'],['SSDBT','bt'],['RAMLIG','bt'],['Transformer_Sec','transformer'],['UNTRMT','transformer'],['MT_BT_Transformer_Connection','transformer']]) assert.equal(category({properties:{tipo:type}}),key);
 assert.equal(category({properties:{tipo_no:'UCBT',CLAS_SUB:'CO1'}}),'com');
 assert.equal(category({properties:{tipo_no:'UCBT'}}),'load');
 assert.equal(category({properties:{tipo:'UNTRMT',CLAS_SUB:'RE1'}}),'transformer');
 assert.equal(category({properties:{}}),'node');
});
test('demonstração cobre as categorias principais',()=>{
 const keys=new Set(demoData().features.map(category));
 for(const key of ['mt','bt','transformer','res','com','ind','load'])assert.ok(keys.has(key),key);
});
