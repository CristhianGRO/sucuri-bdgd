"""Exercise the complete installed service with synthetic, non-customer data."""
import argparse
import io
import json
from pathlib import Path
import time
import urllib.request
import zipfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',required=True)
    parser.add_argument('--data',required=True)
    args=parser.parse_args()
    base=Path(args.data)/'SYNTHETIC_SMOKE';base.mkdir(parents=True,exist_ok=True)
    tables={
        # TEN_NOM é o código TTEN da tensão-base LL; 49 = 13,8 kV no
        # dicionário ANEEL incorporado ao motor.
        'CTMT':'COD_ID,NOME,PAC_INI,TEN_NOM,TEN_OPE\nF1,Synthetic feeder,A,49,1.0\n',
        'SSDMT':'COD_ID,CTMT,PAC_1,PAC_2,PN_CON_1,PN_CON_2,FAS_CON,COMP,TIP_CND\nL1,F1,A,B,N1,N2,ABC,100,C1\n',
        'PONNOT':'COD_ID,X,Y\nN1,-51.0,-30.0\nN2,-51.001,-30.001\n',
        'SEGCON':'COD_ID,R1,X1\nC1,0.3,0.4\n',
    }
    for name,content in tables.items():(base/(name+'.csv')).write_text(content,encoding='utf-8')
    def api(path,body=None):
        request=urllib.request.Request(args.url+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
    request={'kind':'process','args':{'dataset':base.name,'feeder':'F1','crs':'EPSG:4326'}}
    job=api('/api/jobs',request)
    for _ in range(120):
        state=api('/api/jobs/'+job['id'])
        if state['status'] in ('completed','failed'):break
        time.sleep(1)
    assert state['status']=='completed',state
    assert state['result']['nodes']==2,state
    network=api('/api/jobs/'+job['id']+'/network.geojson')
    assert len(network['features'])==3,network
    with urllib.request.urlopen(args.url+'/api/jobs/'+job['id']+'/powerflow.zip') as response:
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert 'report.json' in archive.namelist()
            assert any(name.endswith('.dad') for name in archive.namelist()),archive.namelist()
    saved=api('/api/jobs',request)
    assert saved['cached'] and saved['id']==job['id'],saved
    print('Full packaged pipeline, exports and persistent cache: OK')

if __name__=='__main__':main()
