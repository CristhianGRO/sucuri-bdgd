"""Small native launcher. No datasets are sent to GitHub."""
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser
from .access import Access
from .settings import storage_path, save_storage
from .server import Service, Handler
from .worker import ROOT

SITE = 'https://cristhiangro.github.io/sucuri-bdgd/'

def main():
    root=tk.Tk();root.title('SUCURI Local');root.geometry('640x540');root.minsize(580,520)
    frame=ttk.Frame(root,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='SUCURI Local',font=('Segoe UI',22,'bold')).pack(anchor='w')
    ttk.Label(frame,text='Seus dados e o processamento ficam neste computador.').pack(anchor='w',pady=(4,18))
    folder=tk.StringVar(value=str(storage_path()));status=tk.StringVar(value='Escolha onde guardar as bases e os resultados.')
    code=tk.StringVar(value='--------');state={}
    ttk.Label(frame,text='Pasta dos dados').pack(anchor='w')
    row=ttk.Frame(frame);row.pack(fill='x',pady=8)
    entry=ttk.Entry(row,textvariable=folder);entry.pack(side='left',fill='x',expand=True)
    def choose():
        path=filedialog.askdirectory(title='Pasta para bases BDGD e resultados')
        if path:folder.set(path)
    browse=ttk.Button(row,text='Escolher…',command=choose);browse.pack(side='right',padx=(8,0))
    def start():
        service=None
        try:
            path=save_storage(folder.get())
            access=Access();service=Service(path/'bases',path/'runtime',legacy_data=ROOT/'Dados_BDGD')
            server=ThreadingHTTPServer(('127.0.0.1',8081),partial(Handler,service=service,access=access))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            state.update(server=server,service=service,access=access,thread=thread)
            code.set(access.code);status.set('Serviço ativo. Copie o código e conecte no site (válido por 10 minutos).')
            entry.configure(state='disabled');browse.configure(state='disabled');start_button.configure(state='disabled')
            for button in (copy_button,renew_button,local_button,stop_button):button.configure(state='normal')
        except Exception as exc:
            if service:service.pool.shutdown(wait=False,cancel_futures=True)
            messagebox.showerror('Não foi possível iniciar',f'{exc}\n\nSe a porta 8081 estiver ocupada, feche outra instância do SUCURI Local ou o servidor iniciado no terminal.')
    def stop():
        service=state.get('service')
        if service and any(not j['future'].done() for j in service.jobs.values()):
            messagebox.showinfo('Tarefa em andamento','Aguarde o processamento terminar antes de encerrar o serviço.');return False
        if state:
            state['server'].shutdown();state['server'].server_close();state['thread'].join()
            service.pool.shutdown(wait=False,cancel_futures=True);state.clear()
        code.set('--------');status.set('Serviço parado. Bases e resultados continuam salvos.')
        entry.configure(state='normal');browse.configure(state='normal');start_button.configure(state='normal')
        for button in (copy_button,renew_button,local_button,stop_button):button.configure(state='disabled')
        return True
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=8)
    start_button=ttk.Button(actions,text='Iniciar serviço',command=start);start_button.pack(side='left')
    stop_button=ttk.Button(actions,text='Parar serviço',command=stop,state='disabled');stop_button.pack(side='left',padx=8)
    ttk.Label(frame,text='Código de conexão',font=('Segoe UI',11)).pack(anchor='w',pady=(16,0))
    ttk.Label(frame,textvariable=code,font=('Consolas',28,'bold')).pack(anchor='w')
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=8)
    def copy():root.clipboard_clear();root.clipboard_append(code.get());status.set('Código copiado. Cole no campo “Código do aplicativo” no site.')
    copy_button=ttk.Button(actions,text='Copiar código',command=copy,state='disabled');copy_button.pack(side='left')
    renew_button=ttk.Button(actions,text='Novo código',command=lambda:code.set(state['access'].renew()),state='disabled');renew_button.pack(side='left',padx=8)
    ttk.Button(actions,text='Abrir site',command=lambda:webbrowser.open(SITE)).pack(side='left')
    local_button=ttk.Button(frame,text='Abrir versão local (alternativa de conexão)',command=lambda:webbrowser.open('http://127.0.0.1:8081/'),state='disabled');local_button.pack(anchor='w',pady=8)
    ttk.Label(frame,textvariable=status,wraplength=560).pack(anchor='w',pady=12)
    def close():
        if stop():root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.mainloop()
