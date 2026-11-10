using System;
using System.Windows.Automation;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Text;
using System.Windows.Forms;

partial class Bridge {
 internal class AppFileSource {public string name,binding;public int ordinal,count;}
 static readonly Dictionary<string,AppFileSource> appFileSources=new Dictionary<string,AppFileSource>();
 static readonly Dictionary<string,string> appDownloadedFiles=new Dictionary<string,string>();
 static string FileRoot {get{return Path.Combine(Directory.GetParent(MediaRoot).FullName,"files");}}
 internal static string AppFileName(ANode card){
  var names=All(card).Where(n=>n.role==43).Select(n=>Regex.Match(n.name,@"^(?:正在)?打开 (.+) 的预览$")).Where(m=>m.Success).Select(m=>m.Groups[1].Value).Distinct().ToList();
  return names.Count==1?names[0]:"";
 }
 internal static List<ANode> AppFileCards(ANode root){
  var cards=new List<ANode>();var region=AppConversation(root);if(region==null)return cards;
  foreach(var preview in All(region).Where(n=>n.role==43&&Regex.IsMatch(n.name,@"^(?:正在)?打开 .+ 的预览$"))){
   string name=Regex.Match(preview.name,@"^(?:正在)?打开 (.+) 的预览$").Groups[1].Value;
   var card=preview.parent;while(card!=null&&!All(card).Any(n=>n.role==41&&n.name==name))card=card.parent;
   if(card!=null&&!cards.Contains(card))cards.Add(card);
  }
  return cards;
 }
 static void MarkAppFiles(ANode root){
  appFileSources.Clear();var region=AppConversation(root);if(region==null)return;
  string binding=AppImageBinding(region);var cards=AppFileCards(root);
  foreach(var group in cards.GroupBy(AppFileName)){
   int ordinal=0;foreach(var card in group){
    card.fileRef=Guid.NewGuid().ToString("N");card.fileName=group.Key;
    appFileSources[card.fileRef]=new AppFileSource{name=group.Key,binding=binding,ordinal=ordinal++,count=group.Count()};
   }
   if(group.Count()==1){var card=group.First();foreach(var link in All(region).Where(n=>n.role==30&&n.name=="Open 下载 "+group.Key)){link.fileRef=card.fileRef;link.fileName=group.Key;}}
  }
 }
 internal static bool SafeFileName(string name){return name.Length>0&&name==Path.GetFileName(name)&&!name.Contains(":")&&name.IndexOfAny(Path.GetInvalidFileNameChars())<0&&name!="."&&name!="..";}
 static string LocalFile(string path){
  string full=Path.GetFullPath(path),prefix=Path.GetFullPath(FileRoot)+Path.DirectorySeparatorChar;
  if(!full.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)||!File.Exists(full)||new FileInfo(full).Length>104857600)throw new Exception("文件必须来自程序state/files且不超过100MB");return full;
 }
 [DllImport("shell32.dll")] static extern int SHGetKnownFolderPath(ref Guid id,uint flags,IntPtr token,out IntPtr path);
 static string DownloadsFolder(){Guid id=new Guid("374DE290-123F-4565-9164-39C4925E467B");IntPtr value;int hr=SHGetKnownFolderPath(ref id,0,IntPtr.Zero,out value);if(hr!=0)throw new Exception("无法定位系统下载目录");try{return Marshal.PtrToStringUni(value);}finally{Marshal.FreeCoTaskMem(value);}}
 static bool DownloadNameMatches(string path,string name){return Regex.IsMatch(Path.GetFileName(path),"^"+Regex.Escape(Path.GetFileNameWithoutExtension(name))+@"(?: \(\d+\))?"+Regex.Escape(Path.GetExtension(name))+"$",RegexOptions.IgnoreCase);}
 static Dictionary<string,long> DownloadSnapshot(string folder,string name){var result=new Dictionary<string,long>(StringComparer.OrdinalIgnoreCase);if(Directory.Exists(folder))foreach(string path in Directory.GetFiles(folder).Where(p=>DownloadNameMatches(p,name))){try{result[path]=File.GetLastWriteTimeUtc(path).Ticks;}catch{}}return result;}
 internal static string PlainFilePreview(ANode root,string name){
  if(!new[]{".txt",".csv",".json"}.Contains(Path.GetExtension(name).ToLowerInvariant()))return null;
  var panes=All(root).Where(n=>n.role==38&&n.name==name).ToList();if(panes.Count!=1)return null;
  var nodes=All(panes[0]).ToList();int download=nodes.FindLastIndex(n=>n.role==43&&(n.name=="下载"||n.name=="Download"));if(download<0)return null;
  var text=nodes.Skip(download+1).Where(n=>n.role==41&&(n.state&0x10000)==0).Select(n=>n.name).ToList();return text.Count==1?text[0]:null;
 }
 static object CaptureAppFiles(string[] references,long maxBytes,int timeoutMs){
  if(references.Length>4||maxBytes<1||maxBytes>104857600||timeoutMs<1000||timeoutMs>120000)throw new Exception("附件导出参数超限");
  var files=new List<object>();foreach(string reference in references){
   AppFileSource source;if(!appFileSources.TryGetValue(reference,out source))throw new Exception("附件引用已过期，需要重新读取");
   if(!SafeFileName(source.name))throw new Exception("生成附件的文件名不合法");
   string key=source.binding+"\n"+source.name+"\n"+source.ordinal;
   string saved;if(appDownloadedFiles.TryGetValue(key,out saved)&&File.Exists(saved)){files.Add(new{path=saved,name=source.name});continue;}
   var root=AppRoot();AppGuard(root);var region=AppConversation(root);
   if(region==null||AppImageBinding(region)!=source.binding)throw new Exception("附件对应的提问已变化");
   var matches=AppFileCards(root).Where(c=>AppFileName(c)==source.name).ToList();if(matches.Count!=source.count)throw new Exception("附件列表已变化");
   var card=matches[source.ordinal];
   string folder=Path.Combine(FileRoot,Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);saved=Path.Combine(folder,source.name);
   if(new[]{".txt",".csv",".json"}.Contains(Path.GetExtension(source.name).ToLowerInvariant())){
    if(PlainFilePreview(root,source.name)==null){var preview=Unique(All(card).Where(n=>n.role==43&&(n.name=="打开 "+source.name+" 的预览"||n.name=="正在打开 "+source.name+" 的预览")),"生成附件预览按钮");Click(preview,chatApp);}
    var previewRoot=AppWait(t=>PlainFilePreview(t,source.name)!=null);string text=PlainFilePreview(previewRoot,source.name);
    Thread.Sleep(100);Pump();if(PlainFilePreview(AppRoot(),source.name)!=text)throw new Exception("附件预览内容仍在变化");
    var bytes=new UTF8Encoding(false).GetBytes(text);if(bytes.LongLength>maxBytes)throw new Exception("生成附件超过配置大小上限");
    File.WriteAllBytes(saved,bytes);appDownloadedFiles[key]=saved;files.Add(new{path=saved,name=source.name,source="preview-text"});continue;
   }
   var button=Unique(All(card).Where(n=>n.role==43&&(n.name=="下载文件"||n.name=="Download file")),"生成附件下载按钮");
   string downloads=DownloadsFolder();var before=DownloadSnapshot(downloads,source.name);
   Front(chatApp);try{button.acc.accSelect(1,button.childId);}catch(COMException){}Click(button,chatApp);
   var watch=Stopwatch.StartNew();bool saveRequested=false,previewClicked=false;
   while(watch.ElapsedMilliseconds<timeoutMs){
    Thread.Sleep(80);Pump();
    if(!previewClicked){
     var current=AppRoot();if(appTitle!=""&&AppName(current)!=appTitle)throw new Exception("附件下载期间会话已变化");
     var previews=All(current).Where(n=>n.role==38&&n.name==source.name).ToList();
     if(previews.Count==1){var buttons=All(previews[0]).Where(n=>n.role==43&&(n.name=="下载"||n.name=="Download")).ToList();if(buttons.Count==1){Click(buttons[0],chatApp);previewClicked=true;}}
    }
    foreach(var window in Windows("ChatGPT")){
     if(window==chatApp)continue;ANode dialog;try{dialog=Tree(window);}catch{continue;}
     if(!Regex.IsMatch(dialog.name,@"^(另存为|Save As)$",RegexOptions.IgnoreCase))continue;
     if(saveRequested)continue;
     File.WriteAllText(Path.Combine(Directory.GetParent(FileRoot).FullName,"file-save-dialog.private.json"),Json.Serialize(dialog));
     var inputs=All(dialog).Where(n=>n.role==42&&Regex.IsMatch(n.name,@"^(文件名|File name)",RegexOptions.IgnoreCase)).ToList();
     var saves=All(dialog).Where(n=>n.role==43&&Regex.IsMatch(n.name,@"^(保存|另存为|Save|Save As)(?:\([A-Za-z]\))?$",RegexOptions.IgnoreCase)).ToList();
     if(inputs.Count!=1||saves.Count!=1)throw new Exception("另存为窗口控件不唯一，未保存到其他位置");
     Put(inputs[0],saved,window);Click(saves[0],window);saveRequested=true;
    }
    if(!File.Exists(saved)){
     var fresh=DownloadSnapshot(downloads,source.name).Where(p=>!before.ContainsKey(p.Key)||before[p.Key]!=p.Value).Select(p=>p.Key).ToList();
     if(fresh.Count>1)throw new Exception("出现多个同名新下载，无法确定附件");
     if(fresh.Count==1)try{using(var stream=new FileStream(fresh[0],FileMode.Open,FileAccess.Read,FileShare.None)){if(stream.Length>maxBytes)throw new Exception("生成附件超过配置大小上限");}File.Copy(fresh[0],saved,false);}catch(IOException){}
    }
    if(File.Exists(saved)){
     try{using(var stream=new FileStream(saved,FileMode.Open,FileAccess.Read,FileShare.None)){if(stream.Length>maxBytes)throw new Exception("生成附件超过配置大小上限");}}
     catch(IOException){continue;}
     appDownloadedFiles[key]=saved;files.Add(new{path=saved,name=source.name});break;
    }
   }
   if(!File.Exists(saved)){
    try{var windows=Windows("ChatGPT").Select(h=>new{hwnd=h.ToInt64(),tree=Tree(h)}).ToList();File.WriteAllText(Path.Combine(Directory.GetParent(FileRoot).FullName,"file-download-diagnostic.private.json"),Json.Serialize(windows));}catch{}
    throw new Exception("等待生成附件下载超时，未用旧同名文件代替");
   }
  }
  return new{files=files};
 }
 static string stagedQQFile=null;static int stagedQQFileBefore=-1;
 internal static bool QQRowHasSentFile(ANode row,string name){
  bool sent=All(row).Any(n=>n.role==41&&Regex.IsMatch(n.name,@"(?:B|KB|MB|GB)\s+已发送$"));
  return sent&&All(row).Any(n=>string.Concat(All(n).Where(c=>c.role==41).Select(c=>c.name))==name);
 }
 static int OwnFileCount(string name){return QQRows(ReadMessages()).Where(r=>{var sender=All(r).FirstOrDefault(n=>n.role==20&&n.name.Length>0&&n.children.Count>0&&!n.name.StartsWith("@"));return sender!=null&&sender.name==selfNickname;}).Count(r=>QQRowHasSentFile(r,name));}
 static void QQFileTargetGuard(){var root=QQTree();if(cachedQQHeader.acc.get_accName(cachedQQHeader.childId)!=group)throw new Exception("文件发送时目标群已变化");}
 static bool QQFileSent(){if(stagedQQFile==null||stagedQQFileBefore<0)return false;QQFileTargetGuard();if(QQFileWindows().Any(p=>QQFileSendButtons(p.Value,Path.GetFileName(stagedQQFile),group).Count>0))return false;return OwnFileCount(Path.GetFileName(stagedQQFile))>stagedQQFileBefore;}
 static List<KeyValuePair<IntPtr,ANode>> QQFileWindows(){var result=new List<KeyValuePair<IntPtr,ANode>>();foreach(var window in Windows("QQ")){try{result.Add(new KeyValuePair<IntPtr,ANode>(window,Tree(window)));}catch{}}return result;}
 static object StageQQFile(string path){
  path=LocalFile(path);var root=VerifyGroup();var input=QQInput(root);
  if(Value(input)!=""||All(input).Any(IsQQImage))throw new Exception("QQ已有人工草稿，未粘贴文件");
  stagedQQFileBefore=OwnFileCount(Path.GetFileName(path));stagedQQFile=path;
  Front(qq);FocusQQInput(input);var previous=Clipboard.GetDataObject();uint owned=0;
  try{
   var list=new StringCollection();list.Add(path);Clipboard.SetFileDropList(list);owned=GetClipboardSequenceNumber();
   if(GetForegroundWindow()!=qq)throw new Exception("粘贴文件前QQ焦点已变化");
   commandDraftTouched=true;commandCommitAttempted=true;qqCommitPending=true;
   Key(0x11,true);try{Press(0x56);}finally{Key(0x11,false);}Thread.Sleep(300);Pump();
  }finally{try{if(GetClipboardSequenceNumber()==owned){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}catch{}}
  var windows=QQFileWindows().Select(p=>new{hwnd=p.Key.ToInt64(),tree=p.Value}).ToList();
  File.WriteAllText(Path.Combine(Directory.GetParent(FileRoot).FullName,"qq-file-stage.private.json"),Json.Serialize(new{path=path,before=stagedQQFileBefore,group=group,groupId=groupId,windows=windows}));
  return new{staged=true,confirmed=QQFileSent(),windows=windows};
 }
 static object CommitQQFile(){
  if(stagedQQFile==null)throw new Exception("没有本程序暂存的QQ文件");
  commandCommitAttempted=true;commandDraftTouched=true;
  if(QQFileSent())return new{sent=true,confirmed=true,kind="file"};
  var sends=QQFileWindows().SelectMany(p=>QQFileSendButtons(p.Value,Path.GetFileName(stagedQQFile),group).Select(n=>new KeyValuePair<IntPtr,ANode>(p.Key,n))).ToList();
  if(sends.Count!=1)throw new Exception("SEND_UNCERTAIN: 未找到唯一包含目标群和文件名的文件发送窗口，保留现场");
  QQFileTargetGuard();Click(sends[0].Value,sends[0].Key);
  var watch=Stopwatch.StartNew();while(watch.ElapsedMilliseconds<6000){Thread.Sleep(80);Pump();if(QQFileSent())return new{sent=true,confirmed=true,kind="file"};}
  throw new Exception("SEND_UNCERTAIN: QQ文件已尝试发送但未回读确认，禁止自动重发");
 }
 internal static List<ANode> QQFileSendButtons(ANode root,string name,string target){
  var result=new List<ANode>();foreach(var send in All(root).Where(n=>n.role==43&&n.name=="发送(1)"&&(n.state&1)==0)){
   for(var scope=send.parent;scope!=null;scope=scope.parent){
    if(All(scope).Any(n=>n.name=="消息列表"))break;
    var text=All(scope).Where(n=>n.role==41).Select(n=>n.name).ToList();
    if(text.Contains("发送给 "+target)&&string.Concat(text).Contains(name)){result.Add(send);break;}
   }
  }return result;
 }
 static object ResumeQQFile(string path){
  path=LocalFile(path);var proof=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(Directory.GetParent(FileRoot).FullName,"qq-file-stage.private.json")));
  if(S(proof,"path")!=path||S(proof,"group")!=group)throw new Exception("暂存文件记录与本次任务不一致");
  stagedQQFile=path;stagedQQFileBefore=Convert.ToInt32(proof["before"]);
  if(QQFileSent())return new{sent=true,confirmed=true,kind="file"};
  if(!QQFileWindows().Any(p=>QQFileSendButtons(p.Value,Path.GetFileName(path),group).Count==1))throw new Exception("未发现匹配本程序暂存文件的发送窗口，未重复粘贴");
  return CommitQQFile();
 }
 static object SendQQFile(string path){StageQQFile(path);return CommitQQFile();}

 internal class IncomingQQFile {public string name;public long maxBytes;}
 class QQFileSource {public ANode row;public string fingerprint;public IncomingQQFile info;}
 static readonly Dictionary<string,QQFileSource> incomingQQFiles=new Dictionary<string,QQFileSource>();
 internal static IncomingQQFile QQIncomingInfo(ANode row){
  if(!All(row).Any(n=>n.role==40&&n.name!="图片"))return null;
  var text=All(row).Where(n=>n.role==41).Select(n=>n.name).ToList();
  for(int i=0;i<text.Count;i++){
   var size=Regex.Match(text[i].Trim(),@"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|KiB|MiB|GiB)$",RegexOptions.IgnoreCase);if(!size.Success)continue;
   string name=string.Join("",text.Take(i)).Trim();if(!SafeFileName(name)||!Regex.IsMatch(name,@"\.[\w-]{1,12}$"))continue;
   decimal amount=decimal.Parse(size.Groups[1].Value,System.Globalization.CultureInfo.InvariantCulture);string unit=size.Groups[2].Value.ToUpperInvariant();long scale=unit=="B"?1:unit=="KB"||unit=="KIB"?1024:unit=="MB"||unit=="MIB"?1048576:1073741824;
   int dot=size.Groups[1].Value.IndexOf('.'),precision=dot<0?0:size.Groups[1].Value.Length-dot-1;decimal rounding=unit=="B"?0:(decimal)Math.Pow(10,-precision)/2;
   return new IncomingQQFile{name=name,maxBytes=(long)Math.Ceiling((amount+rounding)*scale)};
  }return null;
 }
 static void MarkQQFiles(List<ANode> rows){incomingQQFiles.Clear();foreach(var row in rows){var info=QQIncomingInfo(row);if(info==null)continue;string reference=Guid.NewGuid().ToString("N");incomingQQFiles[reference]=new QQFileSource{row=row,info=info,fingerprint=ImageFingerprint(row)};row.incomingFiles=new object[]{new{name=info.name,maxBytes=info.maxBytes,@ref=reference}};}}
 static object CaptureQQFile(string reference,long maxBytes,int timeoutMs){
  QQFileSource source;if(!incomingQQFiles.TryGetValue(reference,out source))throw new Exception("文件来源引用已过期");
  if(maxBytes<1||maxBytes>10485760||timeoutMs<1000||timeoutMs>120000)throw new Exception("群文件下载参数超限");
  if(source.info.maxBytes>maxBytes)throw new Exception("文件超过10MB，未下载");
  VerifyGroup();budget=0;var current=Read(source.row.acc,source.row.childId,0,null,false,true);if(ImageFingerprint(current)!=source.fingerprint)throw new Exception("文件消息已变化，未下载");
  var target=All(current).First(n=>n.role==41&&n.name.Length>0);var before=new HashSet<IntPtr>(Windows("QQ"));
  string folder=Path.Combine(FileRoot,"incoming",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);string saved=Path.Combine(folder,source.info.name);
  try{target.acc.accSelect(1,target.childId);}catch{}RightClick(target,qq);
  var timer=Stopwatch.StartNew();ANode action=null;IntPtr menuWindow=qq;
  while(timer.ElapsedMilliseconds<2500){Pump();foreach(var pair in QQFileWindows()){var actions=All(pair.Value).Where(n=>(n.role==12||n.role==43)&&Regex.IsMatch(n.name.Trim(),@"^(另存为|另存为\.\.\.|另存为…|Save as|Save As\.\.\.)$")).ToList();if(actions.Count==1){action=actions[0];menuWindow=pair.Key;break;}}if(action!=null)break;Thread.Sleep(50);}
  if(action==null){Press(0x1b);throw new Exception("找不到群文件另存为入口，未打开或执行文件");}Click(action,menuWindow);
  bool submitted=false;timer.Restart();
  while(timer.ElapsedMilliseconds<timeoutMs){Pump();
  if(!submitted){var handle=GetForegroundWindow();uint sourcePid,dialogPid;GetWindowThreadProcessId(qq,out sourcePid);GetWindowThreadProcessId(handle,out dialogPid);
   if(handle!=qq&&(dialogPid==sourcePid||GetAncestor(handle,3)==qq))try{var dialog=AutomationElement.FromHandle(handle);if(Regex.IsMatch(dialog.Current.Name,@"^(另存为|Save As|保存文件)$",RegexOptions.IgnoreCase)){
    var controls=dialog.FindAll(TreeScope.Descendants,Condition.TrueCondition).Cast<AutomationElement>().ToList();
    var edits=controls.Where(e=>e.Current.ControlType==ControlType.Edit&&Regex.IsMatch(e.Current.Name,@"^(文件名|File name)",RegexOptions.IgnoreCase)).ToList();
    var saves=controls.Where(e=>e.Current.ControlType==ControlType.Button&&Regex.IsMatch(e.Current.Name,@"^(保存|另存为|Save|Save As)(?:\([A-Za-z]\))?$",RegexOptions.IgnoreCase)).ToList();
    if(edits.Count==1&&saves.Count==1){((ValuePattern)edits[0].GetCurrentPattern(ValuePattern.Pattern)).SetValue(saved);((InvokePattern)saves[0].GetCurrentPattern(InvokePattern.Pattern)).Invoke();submitted=true;}
   }}catch(ElementNotAvailableException){}
  }
  foreach(var pair in QQFileWindows()){
   if(before.Contains(pair.Key)||!Regex.IsMatch(pair.Value.name,@"^(另存为|Save As|保存文件)$",RegexOptions.IgnoreCase))continue;
   var inputs=All(pair.Value).Where(n=>n.role==42&&Regex.IsMatch(n.name,@"^(文件名|File name)",RegexOptions.IgnoreCase)).ToList();var buttons=All(pair.Value).Where(n=>n.role==43&&Regex.IsMatch(n.name,@"^(保存|另存为|Save|Save As)(?:\([A-Za-z]\))?$",RegexOptions.IgnoreCase)).ToList();
   if(!submitted&&inputs.Count==1&&buttons.Count==1){Put(inputs[0],saved,pair.Key);Click(buttons[0],pair.Key);submitted=true;}
  }
  if(submitted&&File.Exists(saved)){try{using(var stream=new FileStream(saved,FileMode.Open,FileAccess.Read,FileShare.None)){if(stream.Length>maxBytes)throw new Exception("实际文件超过10MB，未上传");}Thread.Sleep(160);long size=new FileInfo(saved).Length;using(var stream=new FileStream(saved,FileMode.Open,FileAccess.Read,FileShare.None)){if(stream.Length!=size)continue;}return new{file=new{path=saved,name=source.info.name,bytes=size}};}catch(IOException){}}
  Thread.Sleep(80);
  }throw new Exception("等待群文件下载超时，未使用旧同名文件");
 }
 static object AttachAppFile(string path){
  path=LocalFile(path);if(new FileInfo(path).Length>10485760)throw new Exception("输入文件超过10MB");
  var root=AppRoot();AppGuard(root);if(AppGenerating(root)||AppAttachmentCount(root)!=expectedAppAttachments)throw new Exception("普通聊天已有未归属附件，未上传文件");
  int before=expectedAppAttachments;var previous=Clipboard.GetDataObject();uint owned=0;pendingAppImage=path;pendingAppImageBefore=before;commandDraftTouched=true;
  try{var files=new StringCollection();files.Add(path);Clipboard.SetFileDropList(files);owned=GetClipboardSequenceNumber();Click(AppInput(root),chatApp);Key(0x11,true);try{Press(0x56);}finally{Key(0x11,false);}
   root=AppWait(t=>AppAttachmentCount(t)==before+1&&All(AppComposer(t)).Any(n=>n.name.Contains(Path.GetFileName(path)))&&AppReadyToSubmit(t),20000);expectedAppAttachments=before+1;RememberAppComposer(true);pendingAppImage=null;return new{attached=true,count=expectedAppAttachments};
  }finally{RememberAppComposer(true);if(owned!=0&&GetClipboardSequenceNumber()==owned){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}
 }
}
