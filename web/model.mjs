export function feederOf(feature) { return String(feature.properties?.CTMT ?? '').trim(); }
export function validate(data) {
  if (data?.type !== 'FeatureCollection' || !Array.isArray(data.features) || !data.features.length) throw Error('Informe um FeatureCollection GeoJSON não vazio.');
  if(data.features.length > 100000) throw Error('Limite desta versão: 100 mil elementos. Recorte a base por alimentador.');
  const point = p => Array.isArray(p) && p.length >= 2 && p.every(Number.isFinite) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
  const line = p => Array.isArray(p) && p.length >= 2 && p.every(point);
  for (const f of data.features) {
    const g = f.geometry;
    if(f.type !== 'Feature' || !feederOf(f)) throw Error('Cada elemento deve possuir properties.CTMT.');
    if(!g || !(g.type === 'Point' ? point(g.coordinates) : g.type === 'LineString' ? line(g.coordinates) : g.type === 'MultiLineString' ? Array.isArray(g.coordinates) && g.coordinates.length && g.coordinates.every(line) : false)) throw Error('Use Point, LineString ou MultiLineString em longitude/latitude WGS84.');
  }
  return data;
}
export function selected(data, id) {return {type:'FeatureCollection', features:data.features.filter(f=>feederOf(f)===id)};}
export const escapeXML = value => String(value).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c]));
export function toKML(data) {
  const coords = ps => ps.map(p=>p.slice(0,3).join(',')).join(' ');
  const line = ps => `<LineString><coordinates>${coords(ps)}</coordinates></LineString>`;
  return `<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>${data.features.map(f=>{
    const g=f.geometry;
    const geometry=g.type==='Point'?`<Point><coordinates>${coords([g.coordinates])}</coordinates></Point>`:g.type==='LineString'?line(g.coordinates):`<MultiGeometry>${g.coordinates.map(line).join('')}</MultiGeometry>`;
    return `<Placemark><name>${escapeXML(f.properties.COD_ID ?? feederOf(f))}</name><ExtendedData>${Object.entries(f.properties).map(([k,v])=>`<Data name="${escapeXML(k)}"><value>${escapeXML(v)}</value></Data>`).join('')}</ExtendedData>${geometry}</Placemark>`;
  }).join('')}</Document></kml>`;
}
export function demoData(){
  const features=[];
  for(let a=0;a<3;a++){
    const CTMT=`DEMO-0${a+1}`;
    let previous=[-47.07,-22.91];
    for(let i=1;i<=14;i++){
      const next=[-47.07 + Math.sin(a*2.1+.4)*i*.0015, -22.91 + Math.cos(a*2.1+.4)*i*.0012];
      features.push({type:'Feature',properties:{CTMT,COD_ID:`${CTMT}-L${i}`,tipo:i<=7?'SSDMT':'SSDBT',FAS_CON:'ABC',origem:'Demonstração sintética'},geometry:{type:'LineString',coordinates:[previous,next]}});
      features.push({type:'Feature',properties:{CTMT,COD_ID:`${CTMT}-T${i}`,tipo:a===0&&i===1?'Substation':i%5===0?'UNTRMT':'UCBT',CLAS_SUB:['','RE1','CO1','IN1','RU1'][i%5],origem:'Demonstração sintética'},geometry:{type:'Point',coordinates:next}});
      previous=next;
    }
  }
  return {type:'FeatureCollection',features};
}
