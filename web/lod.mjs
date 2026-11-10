/* Nível de detalhe para redes grandes.
   Mantém as linhas da BDGD, mas reduz marcadores que não acrescentam leitura
   no afastamento. Consumidores são agregados em células geográficas e voltam
   a ser barras/flores individuais quando o usuário se aproxima. */
function typeOf(feature){return String(feature.properties?.tipo_no||feature.properties?.tipo||'').toUpperCase();}
function point(feature){return feature.geometry?.type==='Point'&&Array.isArray(feature.geometry.coordinates);}
function within(feature,bounds){
  if(!bounds||!point(feature))return true;
  const [longitude,latitude]=feature.geometry.coordinates;
  return longitude>=bounds.west&&longitude<=bounds.east&&latitude>=bounds.south&&latitude<=bounds.north;
}
function nodeVisible(feature,zoom){
  if(feature.properties?.map_source!=='Nó topológico calculado')return true;
  const type=typeOf(feature);
  if(type==='SUBSTATION')return true;
  if(zoom<13)return false;
  if(zoom<15)return ['PAC_MV','TRANSFORMER_SEC'].includes(type);
  return true;
}
function gridSize(zoom){return zoom<11?.08:zoom<13?.035:.012;}
function rounded(value){return Math.round(value*1e6)/1e6;}
export function consumerClusters(features,zoom){
  const size=gridSize(zoom),groups=new Map();
  for(const feature of features){
    const [longitude,latitude]=feature.geometry.coordinates;
    const cell=`${Math.floor(longitude/size)}:${Math.floor(latitude/size)}`;
    let group=groups.get(cell);
    if(!group){group={longitude:0,latitude:0,count:0,rows:0,classes:{}};groups.set(cell,group);}
    const props=feature.properties??{},count=Number(props.consumer_count??0);
    group.longitude+=longitude;group.latitude+=latitude;group.rows++;
    group.count+=count;
    for(const [name,value] of Object.entries(props.consumer_classes??{}))group.classes[name]=(group.classes[name]??0)+Number(value);
  }
  return [...groups.values()].map((group,index)=>({
    type:'Feature',
    properties:{tipo:'ConsumerCluster',COD_ID:`CONSUMER_CLUSTER_${zoom}_${index}`,consumer_count:group.count,consumer_classes:group.classes,consumer_cluster_size:group.rows,consumer_list_truncated:true},
    geometry:{type:'Point',coordinates:[rounded(group.longitude/group.rows),rounded(group.latitude/group.rows)]}
  }));
}
export function detailData(data,zoom,bounds=null){
  const detail=zoom>=16,anchors=[];
  const features=[];
  for(const feature of data.features){
    if(typeOf(feature)==='CONSUMERANCHOR'){
      if(detail&&within(feature,bounds))features.push(feature);else anchors.push(feature);
      continue;
    }
    if(nodeVisible(feature,zoom)&&within(feature,bounds))features.push(feature);
  }
  if(!detail){
    for(const cluster of consumerClusters(anchors,zoom))if(within(cluster,bounds))features.push(cluster);
  }
  return {type:'FeatureCollection',features};
}
