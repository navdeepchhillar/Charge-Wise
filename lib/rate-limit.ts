const windows=new Map<string,{start:number;count:number}>();
export function limited(req:Request){const key=req.headers.get('cf-connecting-ip')??'local';const now=Date.now();let w=windows.get(key);if(!w||now-w.start>60000){w={start:now,count:0};windows.set(key,w);}if(windows.size>2000)windows.delete(windows.keys().next().value!);return ++w.count>90;}
