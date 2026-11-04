export const categories = {
  substation:{label:'Barra da subestação',color:'#ff454f',shape:'bar'},
  mt:{label:'Média tensão',color:'#62b8ff',shape:'line'},
  bt:{label:'Baixa tensão / ramal',color:'#64d7ae',shape:'line'},
  transformer:{label:'Transformador',color:'#f5cf65',shape:'diamond'},
  res:{label:'RES · Residencial',color:'#f08fb8',shape:'circle'},
  com:{label:'COM · Comercial',color:'#ff9d55',shape:'square'},
  ind:{label:'IND · Industrial',color:'#b49aff',shape:'triangle'},
  load:{label:'Carga · outra / não informada',color:'#d7dde2',shape:'cross'},
  node:{label:'Nó / outro elemento',color:'#84969f',shape:'circle'}
};
export function consumerClass(properties){
  const raw=String(properties.CLAS_SUB??properties.classe_consumidor??properties.classe??'').trim().toUpperCase();
  if(/^(RE\d*|RES|RESIDENCIAL)$/.test(raw))return 'res';
  if(/^(CO\d*|COM|COMERCIAL)$/.test(raw))return 'com';
  if(/^(IN\d*|IND|INDUSTRIAL)$/.test(raw))return 'ind';
  return 'load';
}
export function category(feature){
  const p=feature.properties??{};
  const type=String(p.tipo_no||p.tipo||'').toUpperCase().split('.').pop();
  if(['SUBSTATION','SUBESTACAO','SUBESTAÇÃO'].includes(type))return 'substation';
  if(['UCBT','UCMT','UCAT','LOAD','CONSUMER','CARGA'].includes(type))return consumerClass(p);
  if(['UNTRMT','UNTRAT','TRANSFORMER_SEC','MT_BT_TRANSFORMER_CONNECTION','TRANSFORMER'].includes(type))return 'transformer';
  if(['SSDMT','MV_LINE','MV_SWITCH','UNSEMT','PAC_MV','MT_NODE'].includes(type))return 'mt';
  if(['SSDBT','RAMLIG','UNSEBT','PAC_LV','PAC_RAMLIG','BT_NODE'].includes(type))return 'bt';
  if(feature.geometry?.type==='Point' && p.CLAS_SUB!=null)return consumerClass(p);
  return 'node';
}
export function symbolSVG(key){
  const {color,shape}=categories[key]??categories.node;
  const geometry={bar:'<rect x="1" y="4" width="14" height="8" rx="1"/>',circle:'<circle cx="8" cy="8" r="5"/>',square:'<rect x="3" y="3" width="10" height="10" rx="1"/>',triangle:'<path d="M8 2 L14 13 L2 13 Z"/>',diamond:'<path d="M8 1 L15 8 L8 15 L1 8 Z"/>',cross:'<path d="M6 2 H10 V6 H14 V10 H10 V14 H6 V10 H2 V6 H6 Z"/>',line:'<path d="M1 8 H15" fill="none" stroke-width="3"/>'}[shape];
  return `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="${color}" stroke="${shape==='line'?color:'#172024'}" stroke-width="1.2">${geometry}</svg>`;
}
