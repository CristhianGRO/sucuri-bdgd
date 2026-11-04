const local=['127.0.0.1','localhost'].includes(location.hostname);
let base=local?location.origin:'http://127.0.0.1:8081';
let token=sessionStorage.getItem('sucuri-token')||'';
export async function request(path,options={}){
 let response;
 try{response=await fetch(base+path,{...options,headers:{...options.headers,...(!local&&token?{Authorization:`Bearer ${token}`}:{})}});}
 catch{throw Error('Não foi possível acessar o SUCURI Local. Abra o aplicativo, inicie o serviço e permita o acesso à rede local no navegador. Se persistir, use “Abrir versão local” no aplicativo.');}
 if(!response.ok){let message;try{message=(await response.json()).error;}catch{}throw Error(message||`Serviço indisponível (${response.status})`);}
 return response;
}
export async function api(path,options){return (await request(path,options)).json();}
export async function pair(code){const result=await api('/api/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});token=result.token;sessionStorage.setItem('sucuri-token',token);}
export async function downloadResult(path,filename='powerflow.zip'){
 const blob=await (await request(path)).blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
export const isLocal=local;
