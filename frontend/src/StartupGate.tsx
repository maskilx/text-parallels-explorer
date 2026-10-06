import {useEffect, useState, type ReactNode} from 'react';
import {Layers3, LoaderCircle} from 'lucide-react';

export type PreparationState = {
 status: 'preparing' | 'ready' | 'failed';
 phase: string;
 message: string;
 percent: number | null;
 completed?: number;
 total?: number;
 cache_hit?: boolean;
 error?: string | null;
};

export function PreparationBar({state}: {state: PreparationState}) {
 const percent = state.percent === null ? null : Math.min(100, Math.max(0, state.percent));
 return <section className="preparation-progress" aria-label="Workspace preparation">
  <div className="preparation-caption"><p role="status">{state.message}</p><span>{percent===null?'Working…':`${Math.round(percent)}%`}</span></div>
  <div className={'preparation-track '+(percent===null?'indeterminate':'')} role="progressbar" aria-label="Preparation progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent??undefined} aria-valuetext={state.message}>
   <div style={percent===null?undefined:{width:`${percent}%`}}/>
  </div>
 </section>;
}

export default function StartupGate({children}: {children: ReactNode}) {
 const [state,setState]=useState<PreparationState>({status:'preparing',phase:'connecting',message:'Connecting to your workspace',percent:null});
 const [connectionError,setConnectionError]=useState('');
 const [retrying,setRetrying]=useState(false);
 useEffect(()=>{
  if(state.status==='ready')return;
  let active=true;
  const controller=new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  async function poll(){
   try{
    const response=await fetch('/api/startup',{signal:controller.signal});
    if(!response.ok)throw new Error('Unable to read workspace progress');
    const next:PreparationState=await response.json();
    if(active){setState(next);setConnectionError('');}
    if(next.status==='ready')return;
   }catch(error){if(active&&(error as Error).name!=='AbortError')setConnectionError('Unable to reach the server. Checking again…');}
   if(active)timer=setTimeout(poll,700);
  }
  void poll();
  return()=>{active=false;controller.abort();clearTimeout(timer);};
 },[state.status==='ready']);
 async function retry(){
  setRetrying(true);
  try{
   const response=await fetch('/api/startup/retry',{method:'POST'});
   if(!response.ok)throw new Error('Retry could not start. Please check the server log.');
   setState({status:'preparing',phase:'checking',message:'Checking the workspace again',percent:0});setConnectionError('');
  }catch(error){setConnectionError((error as Error).message);}finally{setRetrying(false);}
 }
 if(state.status==='ready')return children;
 return <main className="startup-screen"><section className="startup-card">
  <div className="startup-brand"><Layers3 size={30}/><span>Text Parallels Explorer</span></div>
  <div className="eyebrow">LOCAL RESEARCH WORKSPACE</div>
  <h1>{state.status==='failed'?'Preparation needs attention':'Preparing your workspace'}</h1>
  <p className="startup-description">Finding textual parallels and preparing semantic suggestions with a local model. Your browser will open the workspace automatically when it is ready.</p>
  {state.status==='failed'?<div role="alert" className="startup-error"><p>{state.error||state.message}</p><button className="button primary" disabled={retrying} onClick={retry}>{retrying?<LoaderCircle className="spin" size={16}/>:null}Retry preparation</button></div>:<PreparationBar state={state}/>}
  {connectionError?<p role="alert">{connectionError}</p>:null}
  <p className="startup-footnote">First use downloads the model weights and computes passage vectors. Later launches reuse saved results when the texts and settings are unchanged. No paid API is used.</p>
 </section></main>;
}
