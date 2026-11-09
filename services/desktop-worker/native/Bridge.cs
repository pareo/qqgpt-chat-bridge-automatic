// Windows accessibility bridge. No QQ injection, database access or browser cookies.
using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using Accessibility;
using System.Windows.Forms;
using System.Windows.Automation;

class ANode {
 public int role, state;
 public string name="", value="", description="";
 public bool hasValue;
 public string mediaRef="";
 public string fileRef="",fileName="";
 public object[] incomingFiles=new object[0];
 public List<ANode> children=new List<ANode>();
 [ScriptIgnore] public IAccessible acc;
 [ScriptIgnore] public int childId;
 [ScriptIgnore] public ANode parent;
}
partial class Bridge {
 delegate bool EnumProc(IntPtr hwnd,IntPtr arg);
 delegate void WinEventProc(IntPtr hook,uint ev,IntPtr hwnd,int obj,int child,uint thread,uint time);
 [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb,IntPtr arg);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
 [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(POINT point);
 [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr hwnd,uint flags);
 [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT point);
 [DllImport("user32.dll")] static extern uint SendInput(uint n,INPUT[] a,int size);
 [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint min,uint max,IntPtr mod,WinEventProc cb,uint process,uint thread,uint flags);
 [DllImport("user32.dll")] static extern bool UnhookWinEvent(IntPtr hook);
 [DllImport("user32.dll")] static extern bool PeekMessage(out MSG msg,IntPtr hwnd,uint min,uint max,uint flags);
 [DllImport("user32.dll")] static extern bool TranslateMessage(ref MSG msg);
 [DllImport("user32.dll")] static extern IntPtr DispatchMessage(ref MSG msg);
 [DllImport("oleacc.dll")] static extern int AccessibleObjectFromWindow(IntPtr h,uint id,ref Guid iid,[MarshalAs(UnmanagedType.Interface)]out IAccessible a);
 [DllImport("oleacc.dll")] static extern int AccessibleChildren(IAccessible a,int start,int count,[Out,MarshalAs(UnmanagedType.LPArray,SizeParamIndex=2)]object[] children,out int obtained);
 [StructLayout(LayoutKind.Sequential)] struct MSG {public IntPtr hwnd;public uint message;public UIntPtr wParam;public IntPtr lParam;public uint time;public int x,y;}
 [StructLayout(LayoutKind.Sequential)] struct INPUT {public uint type;public UNION u;}
 [StructLayout(LayoutKind.Sequential)] struct POINT {public int x,y;public POINT(int xx,int yy){x=xx;y=yy;}}
 [StructLayout(LayoutKind.Explicit)] struct UNION {[FieldOffset(0)]public MOUSE mi;[FieldOffset(0)]public KEY ki;}
 [StructLayout(LayoutKind.Sequential)] struct MOUSE {public int dx,dy;public uint data,flags,time;public UIntPtr extra;}
 [StructLayout(LayoutKind.Sequential)] struct KEY {public ushort vk,scan;public uint flags,time;public UIntPtr extra;}
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer{MaxJsonLength=8000000};
 static readonly ConcurrentQueue<string> Commands=new ConcurrentQueue<string>();
 static readonly object OutputLock=new object();
 static bool running=true;
 static string group="示例群",groupId="20000001",origin="https://chat.example.com",model="gpt-6.1-sol";
 static string selfNickname="",sendShortcut="enter";
 static IntPtr qq,chrome,hook,chatApp;
 static string appTitle="";
 static ANode cachedQQHeader,cachedQQList,cachedQQInput,cachedAddress,cachedDocument,cachedBrowserInput;
 static WinEventProc eventCallback;
 static long lastEvent;
 static int budget;
 static bool skipMessages;
 static void Emit(object obj){lock(OutputLock){Console.WriteLine(Json.Serialize(obj));Console.Out.Flush();}}
 static string S(Dictionary<string,object>d,string k,string fallback=""){return d.ContainsKey(k)?Convert.ToString(d[k]):fallback;}
 static bool B(Dictionary<string,object>d,string k){return d.ContainsKey(k)&&Convert.ToBoolean(d[k]);}
 static bool commandCommitAttempted=false,commandDraftTouched=false;
 [STAThread] static void Main(){
  Console.InputEncoding=new UTF8Encoding(false);Console.OutputEncoding=new UTF8Encoding(false);SetProcessDPIAware();
  new Thread(delegate(){string line;while((line=Console.ReadLine())!=null)Commands.Enqueue(line);running=false;}){IsBackground=true}.Start();
  Emit(new{eventName="ready",version=1});
  while(running){string line;while(Commands.TryDequeue(out line)){int id=0;commandCommitAttempted=false;commandDraftTouched=false;try{var d=Json.Deserialize<Dictionary<string,object>>(line);id=Convert.ToInt32(d["id"]);var sw=Stopwatch.StartNew();object data=Execute(d);Emit(new{id=id,ok=true,ms=sw.ElapsedMilliseconds,data=data});}catch(Exception e){Emit(new{id=id,ok=false,error=e.Message,commitAttempted=commandCommitAttempted,draftTouched=commandDraftTouched});}}
   MSG msg;while(PeekMessage(out msg,IntPtr.Zero,0,0,1)){TranslateMessage(ref msg);DispatchMessage(ref msg);}Thread.Sleep(8);
  }
  if(hook!=IntPtr.Zero)UnhookWinEvent(hook);
 }
 static string WorkerStateRoot {get {string value=Environment.GetEnvironmentVariable("DAIFEILONG_WORKER_STATE_DIR");if(String.IsNullOrEmpty(value))throw new Exception("Worker state directory is required");return System.IO.Path.GetFullPath(value);}}
 static object Execute(Dictionary<string,object>d){string op=S(d,"op");switch(op){
   case "app.inspect":return AppInspect(S(d,"title"));
   case "app.prepare":return AppPrepare(S(d,"title"),S(d,"model","current"),S(d,"effort","current"),B(d,"verifySettings"));
   case "app.state":return AppState();
   case "app.copyReply":return CopyAppReply(S(d,"expected"));
   case "app.fill":return AppFill(S(d,"text"));
   case "app.attachFile":return AttachAppFile(S(d,"path"));
   case "app.attachImage":return AttachAppImage(S(d,"path"));
   case "app.captureImages":return CaptureAppImages(((System.Collections.IEnumerable)d["refs"]).Cast<object>().Select(Convert.ToString).ToArray());
   case "app.captureFiles":return CaptureAppFiles(((System.Collections.IEnumerable)d["refs"]).Cast<object>().Select(Convert.ToString).ToArray(),d.ContainsKey("maxBytes")?Convert.ToInt64(d["maxBytes"]):52428800,d.ContainsKey("timeoutMs")?Convert.ToInt32(d["timeoutMs"]):30000);
   case "app.submit":return AppSubmit(S(d,"expected"));
   case "quit":running=false;return new{stopped=true};
 default:throw new Exception("Operation unavailable in ChatGPT worker: "+op);
 }}
 static IAccessible Root(IntPtr h){Guid iid=new Guid("618736e0-3c3d-11cf-810c-00aa00389b71");IAccessible a;int hr=AccessibleObjectFromWindow(h,0xfffffffc,ref iid,out a);if(hr!=0||a==null)throw new Exception("无法读取窗口辅助功能接口");return a;}
 static List<IntPtr> Windows(string app){var list=new List<IntPtr>();EnumWindows(delegate(IntPtr h,IntPtr x){if(!IsWindowVisible(h))return true;uint p;GetWindowThreadProcessId(h,out p);try{if(Process.GetProcessById((int)p).ProcessName.Equals(app,StringComparison.OrdinalIgnoreCase))list.Add(h);}catch{}return true;},IntPtr.Zero);return list;}
 static ANode Read(IAccessible a,int id,int depth,ANode parent,bool skipDocuments,bool light=false){
  if(depth>55||++budget>5000)throw new Exception("控件树过大，停止操作");
  var n=new ANode{acc=a,childId=id,parent=parent};
  n.role=Convert.ToInt32(a.get_accRole(id));n.name=a.get_accName(id)??"";
  string raw=(!light||n.role==30||n.role==15)?a.get_accValue(id):null;n.hasValue=raw!=null;n.value=raw??"";
  if(!light){n.description=a.get_accDescription(id)??"";n.state=Convert.ToInt32(a.get_accState(id));}
  if(id!=0||(skipDocuments&&n.role==15)||(skipMessages&&n.name=="消息列表"))return n;
  int count=a.accChildCount;if(count>1200)throw new Exception("单层控件过多，停止操作");if(count==0)return n;
  var items=new object[count];int got;AccessibleChildren(a,0,count,items,out got);
  for(int i=0;i<got;i++){try{var c=items[i]as IAccessible;if(c!=null)n.children.Add(Read(c,0,depth+1,n,skipDocuments,light));else if(items[i]is int)n.children.Add(Read(a,(int)items[i],depth+1,n,skipDocuments,light));}catch(COMException){throw new Exception("窗口正在更新，稍后重新读取");}}
  return n;
 }
 static ANode Tree(IntPtr h,bool skipDocuments=false,bool metadataOnly=false){budget=0;bool before=skipMessages;skipMessages=metadataOnly;try{return Read(Root(h),0,0,null,skipDocuments);}finally{skipMessages=before;}}
 static IEnumerable<ANode> All(ANode n){yield return n;foreach(var c in n.children)foreach(var e in All(c))yield return e;}
 static ANode Unique(IEnumerable<ANode> nodes,string label){var a=nodes.ToList();if(a.Count!=1)throw new Exception(label+"不唯一或不存在 ("+a.Count+")");return a[0];}
 static string Value(ANode n){return (n.acc.get_accValue(n.childId)??"").Replace("\r\n","\n").Trim();}
 // Retry only observations while QQ remounts its controls. Never replay a click,
 // paste, member selection or Send key when an operation's outcome is uncertain.
 internal static T QQReadStable<T>(Func<T> read,Action<int> pause=null){
  for(int attempt=0;;attempt++){
   try{return read();}
   catch(Exception error){if(attempt>=3||!(error is COMException||error.Message=="窗口正在更新，稍后重新读取"))throw;
    int delay=35*(attempt+1);if(pause!=null)pause(delay);else{Thread.Sleep(delay);Pump();}}
  }
 }
 static ANode QQMetadataTree(IntPtr window){return QQReadStable(()=>Tree(window,false,true));}
 static void Front(IntPtr h){if(!IsWindow(h))throw new Exception("窗口已关闭");if(GetForegroundWindow()==h)return;SetForegroundWindow(h);if(GetForegroundWindow()!=h){Key(0x12,true);SetForegroundWindow(h);Key(0x12,false);Thread.Sleep(35);}if(GetForegroundWindow()!=h)throw new Exception("无法获得窗口焦点，请停止拖动/切换窗口后重试");}
 static void Key(ushort vk,bool down){var input=new INPUT{type=1,u=new UNION{ki=new KEY{vk=vk,flags=down?0u:2u}}};if(SendInput(1,new[]{input},Marshal.SizeOf(typeof(INPUT)))!=1)throw new Exception("键盘输入被系统阻止");}
 static void Press(ushort vk){Key(vk,true);Key(vk,false);}
 static void Click(ANode n,IntPtr h){Front(h);int x,y,w,hei;n.acc.accLocation(out x,out y,out w,out hei,n.childId);if(w<1||hei<1)throw new Exception("控件不可见");SetCursorPos(x+w/2,y+hei/2);var a=new[]{new INPUT{type=0,u=new UNION{mi=new MOUSE{flags=2}}},new INPUT{type=0,u=new UNION{mi=new MOUSE{flags=4}}}};if(SendInput(2,a,Marshal.SizeOf(typeof(INPUT)))!=2)throw new Exception("鼠标输入被系统阻止");}
 static void Invoke(ANode n,IntPtr h){Front(h);try{n.acc.accDoDefaultAction(n.childId);}catch{Click(n,h);}}
 static void Put(ANode n,string text,IntPtr h){Front(h);try{n.acc.set_accValue(n.childId,text);}catch{Click(n,h);if(GetForegroundWindow()!=h)throw new Exception("焦点已变化");Key(0x11,true);Press(0x41);Key(0x11,false);foreach(char c in text){var a=new[]{new INPUT{type=1,u=new UNION{ki=new KEY{scan=c,flags=4}}},new INPUT{type=1,u=new UNION{ki=new KEY{scan=c,flags=6}}}};if(SendInput(2,a,Marshal.SizeOf(typeof(INPUT)))!=2)throw new Exception("文本输入未完成");}}
  var sw=Stopwatch.StartNew();while(sw.ElapsedMilliseconds<1200){if(Value(n)==text.Trim())return;Thread.Sleep(20);}throw new Exception("写入后内容校验失败，未执行发送");
 }
 static ANode QQWindowTree(){
  if(qq==IntPtr.Zero||!IsWindow(qq)){qq=IntPtr.Zero;for(int attempt=0;attempt<4&&qq==IntPtr.Zero;attempt++){foreach(var h in Windows("QQ")){var t=QQMetadataTree(h);if(All(t).Any(n=>n.name=="消息列表")){if(qq!=IntPtr.Zero)throw new Exception("检测到多个 QQ 聊天窗口，请仅保留目标群窗口");qq=h;}}if(qq==IntPtr.Zero){Thread.Sleep(150);Pump();}}if(qq==IntPtr.Zero)throw new Exception("找不到 QQ 聊天窗口；请在已登录的桌面运行程序");WatchQQ();}
  return QQMetadataTree(qq);
 }
 static ANode BindQQTree(ANode root){cachedQQHeader=RequireGroupName(root,group);cachedQQList=Unique(All(root).Where(n=>n.name=="消息列表"),"消息列表");cachedQQInput=QQInput(root);return root;}
 static ANode QQTree(){return BindQQTree(QQWindowTree());}
 static void WatchQQ(){if(hook!=IntPtr.Zero)UnhookWinEvent(hook);uint pid;GetWindowThreadProcessId(qq,out pid);eventCallback=delegate(IntPtr hh,uint ev,IntPtr hwnd,int obj,int child,uint tid,uint time){long now=Stopwatch.GetTimestamp();if((now-lastEvent)*1000/Stopwatch.Frequency<45)return;lastEvent=now;Emit(new{eventName="qq-change"});};hook=SetWinEventHook(0x8000,0x8018,IntPtr.Zero,eventCallback,pid,0,0);}
 static ANode QQInput(ANode root){return Unique(All(root).Where(n=>n.role==20&&n.hasValue&&n.value.Length>0&&(n.state&0x100000)!=0&&(n.state&0x40)==0),"QQ 输入框");}
 static List<ANode> QQRows(ANode root){var list=Unique(All(root).Where(n=>n.name=="消息列表"),"消息列表");var node=list.children.FirstOrDefault();if(node==null)return new List<ANode>();for(int i=0;i<8&&node.children.Count==1;i++)node=node.children[0];return node.children;}
 static ANode ReadMessages(){return QQReadStable(()=>{budget=0;return Read(cachedQQList.acc,cachedQQList.childId,0,null,false,true);});}
 static object QQSnapshot(){ANode root=null;string draft="";if(cachedQQList!=null&&IsWindow(qq)){try{if(cachedQQHeader.acc.get_accName(cachedQQHeader.childId)!=group)throw new Exception("群会话已变化");if(cachedQQList.acc.get_accName(cachedQQList.childId)!="消息列表")throw new Exception("消息列表已变化");draft=Value(cachedQQInput);root=ReadMessages();}catch{root=null;}}if(root==null){QQTree();draft=Value(cachedQQInput);root=ReadMessages();}var rows=QQRows(root);MarkQQImages(rows);MarkQQFiles(rows);return new{groupName=group,groupId=groupId,hwnd=qq.ToInt64(),draft=draft,rows=rows};}
 static void Pump(){MSG msg;while(PeekMessage(out msg,IntPtr.Zero,0,0,1)){TranslateMessage(ref msg);DispatchMessage(ref msg);}}
 // Group-name-only routing: no title-card click, numeric discovery or numeric proof.
 static ANode VerifyGroup(){return QQTree();}
 static void PutQQ(ANode input,string text,string expectedBefore=null){
  // QQ's rich editor can display accValue text without updating its internal document.
  // A real paste follows the same editor input path as a user and preserves paragraphs.
  Front(qq);Click(input,qq);Thread.Sleep(60);Pump();FocusQQInput(input);
  if(expectedBefore!=null&&(Value(input)!=expectedBefore||GetForegroundWindow()!=qq))throw new Exception("清理前QQ草稿或焦点已变化，未覆盖");
  if(text.Length==0){Key(0x11,true);try{Press(0x41);}finally{Key(0x11,false);}Press(0x08);var clear=Stopwatch.StartNew();while(clear.ElapsedMilliseconds<1500){Thread.Sleep(25);Pump();if(Value(input)=="")return;}throw new Exception("QQ 清空草稿未确认");}
  var previous=Clipboard.GetDataObject();
  try{
   Clipboard.SetText(text,TextDataFormat.UnicodeText);if(GetForegroundWindow()!=qq)throw new Exception("QQ 焦点已变化，未粘贴");Key(0x11,true);try{Thread.Sleep(30);Press(0x41);Thread.Sleep(50);if(GetForegroundWindow()!=qq)throw new Exception("QQ 焦点已变化，未粘贴");Press(0x56);Thread.Sleep(30);}finally{Key(0x11,false);}
   var sw=Stopwatch.StartNew();string observed="";bool refreshed=false;while(sw.ElapsedMilliseconds<2500){Thread.Sleep(35);Pump();observed=Value(input);if(sw.ElapsedMilliseconds>=180&&QQDraftText(observed)==QQDraftText(text))return;if(!refreshed&&sw.ElapsedMilliseconds>=350){input=QQInput(QQTree());refreshed=true;}}
   throw new Exception("QQ 粘贴内容校验失败，未执行发送；期望字符="+text.Length+"，实际字符="+observed.Length+"，前台一致="+(GetForegroundWindow()==qq));
  }finally{try{if(Clipboard.ContainsText(TextDataFormat.UnicodeText)&&Clipboard.GetText(TextDataFormat.UnicodeText)==text){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}catch{}}
 }
 static object QQFill(string text){if(text.Length==0||text.Length>3000)throw new Exception("回复长度不合法");var root=VerifyGroup();var input=QQInput(root);if(Value(input)!="")throw new Exception("QQ 输入框存在人工草稿，暂停以避免覆盖");BeginOwnedQQDraft(text);commandDraftTouched=true;ComposeQQText(input,text);RememberOwnedQQDraft();return new{filled=true,text=text,nativeMentions=NativeDraftNames.ToArray()};}
 static object QQClear(string expected){var input=QQInput(QQTree());if(Value(input)!=expected.Trim())throw new Exception("草稿与测试文本不符，拒绝清空");commandDraftTouched=true;PutQQ(input,"");return new{cleared=true};}
 static object QQReplace(string expected,string text){if(text.Length==0||text.Length>3000)throw new Exception("修复后的长度不合法");var input=QQInput(VerifyGroup());if(!QQTextMatches(Value(input),expected))throw new Exception("草稿已被人工修改，拒绝替换");BeginOwnedQQDraft(text);RememberOwnedQQDraft();commandDraftTouched=true;PutQQ(input,"");RememberOwnedQQDraft();ComposeQQText(input,text);RememberOwnedQQDraft();return new{replaced=true};}
 static string QQDraftText(string text){return Regex.Replace(text.Replace("\r\n","\n").Trim(),@"\n{2,}","\n");}
 static string CanonicalText(string text){return Regex.Replace(text,@"\s+","");}
 static int ReplyCount(List<ANode> rows,string text){string expected=CanonicalText(text);return rows.Count(r=>(selfNickname==""||All(r).Any(n=>n.role==20&&n.name==selfNickname))&&CanonicalText(LeafText(r)).Contains(expected));}
 static object FocusQQInput(ANode input){
  Front(qq);try{input.acc.accSelect(1,input.childId);}catch{Click(input,qq);}
  var sw=Stopwatch.StartNew();int state=0;while(sw.ElapsedMilliseconds<700){Pump();state=Convert.ToInt32(input.acc.get_accState(input.childId));if(GetForegroundWindow()==qq&&(state&4)!=0)return new{focused=true,state=state};Thread.Sleep(20);}
  throw new Exception("QQ 编辑框未获得键盘焦点，未执行发送；state="+state);
 }
 static object QQSend(string text,bool draftReady){
  qqAttemptText=text;qqAttemptBefore=-1;
  if(draftReady){var proof=VerifyGroup();var input=QQInput(proof);var actual=DraftMentionLabels(input).Select(n=>n.Substring(1)).ToList();var planned=nativeMentions?MentionPlan(text,QQMemberNames(proof).Concat(CachedMemberNames()).Concat(actual)).Where(p=>p.name!=null).Select(p=>p.name):Enumerable.Empty<string>();if(!OptionalMentionNamesMatch(actual,planned))throw new Exception("MENTION_PROOF_FAILED: 草稿含计划外提及，未发送");NativeDraftNames=actual;VerifyNativeDraft(input);if(!QQTextMatches(Value(input),text))throw new Exception("QQ 草稿已变化，拒绝发送");}else QQFill(text);
  Front(qq);Press(0x1b);Thread.Sleep(65);Pump();
  var root=QQTree();if(!QQTextMatches(Value(QQInput(root)),text))throw new Exception("发送前草稿校验失败");VerifyNativeDraft(cachedQQInput);var rows=QQRows(ReadMessages());int before=ReplyCount(rows,text);
  qqAttemptBefore=before;var send=Unique(All(root).Where(n=>n.role==43&&n.name=="发送"),"QQ 发送按钮");if((send.state&1)!=0)throw new Exception("QQ 发送按钮不可用");FocusQQInput(cachedQQInput);
  if(!QQTextMatches(Value(cachedQQInput),text)||GetForegroundWindow()!=qq)throw new Exception("QQ 焦点或草稿已变化，未执行发送");VerifyNativeDraft(cachedQQInput);
  // Native mentions and multiline drafts can consume Enter as an editor action.
  // Click the exact enabled Send button the user uses, then observe only; never
  // switch to another commit action if the result becomes uncertain.
  commandCommitAttempted=true;qqCommitPending=true;Click(send,qq);
  var sw=Stopwatch.StartNew();while(sw.ElapsedMilliseconds<3500){Thread.Sleep(45);Pump();if(cachedQQHeader.acc.get_accName(cachedQQHeader.childId)!=group)throw new Exception("SEND_UNCERTAIN: 发送确认时群会话已变化");var after=QQRows(ReadMessages());if(Value(cachedQQInput)==""&&ReplyCount(after,text)>before){qqCommitPending=false;return new{sent=true,confirmed=true};}}
  throw new Exception("SEND_UNCERTAIN: 已尝试发送但未确认，禁止自动重发，请检查群记录");
 }
 static string LeafText(ANode n){return string.Join("\n",All(n).Where(x=>x.role==41).Select(x=>x.name));}
 static bool Allowed(string url){Uri u;return Uri.TryCreate(url,UriKind.Absolute,out u)&&u.GetLeftPart(UriPartial.Authority).Equals(origin,StringComparison.OrdinalIgnoreCase)&&u.Scheme=="https";}
 static object AppInspect(string title=""){var root=title==""?AppRoot():OpenAppConversation(title);return new{hwnd=chatApp.ToInt64(),tree=root};}
 static object AppInspectModel(string title){OpenAppConversation(title);var root=AppRoot();AppGuard(root);Click(AppPicker(root),chatApp);Thread.Sleep(180);Pump();try{return new{hwnd=chatApp.ToInt64(),tree=AppRoot()};}finally{CloseAppMenus();}}
 internal static bool HasAppDocument(ANode root){return All(root).Any(n=>n.role==15&&n.value=="app://-/index.html");}
 internal static ANode ReadReadyApp(Func<ANode> read,Action wake,Action<int> pause){
  ANode root=null;
  for(int attempt=0;attempt<8;attempt++){
   root=read();if(HasAppDocument(root))return root;
   if(attempt==0)wake();
   if(attempt<7)pause(120);
  }
  return root;
 }
 static AutomationElement appAutomation;
 static void WakeAppAccessibility(IntPtr h){
  // Chromium can initially expose only an empty MSAA document. Request its
  // Windows UI Automation provider, then wait for the existing MSAA tree.
  // This reads controls only; it never changes focus, drafts or system settings.
  appAutomation=AutomationElement.FromHandle(h);
  if(appAutomation!=null)appAutomation.FindAll(TreeScope.Descendants,Condition.TrueCondition);
 }
 static ANode ReadAppWindow(IntPtr h){return ReadReadyApp(()=>{
  for(int i=0;;i++){try{return Tree(h);}catch(Exception e){if(i>=2||e.Message!="窗口正在更新，稍后重新读取")throw;Thread.Sleep(45);Pump();}}
 },()=>WakeAppAccessibility(h),ms=>{Thread.Sleep(ms);Pump();});}
 static ANode AppRoot(){
  if(chatApp!=IntPtr.Zero&&IsWindow(chatApp)){var cached=ReadAppWindow(chatApp);if(HasAppDocument(cached))return cached;chatApp=IntPtr.Zero;}
  var candidates=new List<KeyValuePair<IntPtr,ANode>>();
  int seen=0;string lastReadError="";
  for(int attempt=0;attempt<2&&candidates.Count==0;attempt++){var windows=Windows("ChatGPT");seen=windows.Count;if(windows.Count==0)break;foreach(var h in windows){try{var tree=ReadAppWindow(h);if(HasAppDocument(tree))candidates.Add(new KeyValuePair<IntPtr,ANode>(h,tree));}catch(Exception e){lastReadError=e.Message;}}if(candidates.Count==0){Thread.Sleep(150);Pump();}}
  if(candidates.Count>1&&appTitle!="")candidates=candidates.Where(c=>AppName(c.Value)==appTitle).ToList();
  if(candidates.Count!=1)throw new Exception("APP_UNAVAILABLE: "+(seen>0&&candidates.Count==0?"ChatGPT窗口已打开，但聊天页面控件尚未就绪"+(lastReadError==""?"":"（"+lastReadError+"）"):"需要一个可读取的目标 ChatGPT 主窗口")+"，当前候选数="+candidates.Count);
  chatApp=candidates[0].Key;return candidates[0].Value;
 }
 static ANode AppDoc(ANode root){return Unique(All(root).Where(n=>n.role==15&&n.value=="app://-/index.html"),"ChatGPT 应用页面");}
 static string AppName(ANode root){return AppDoc(root).name;}
 static ANode AppInput(ANode root){
  // A Work composer is a different control; never type into it, even on the ChatGPT sidebar.
  return Unique(All(root).Where(n=>n.role==42&&(n.name=="询问 ChatGPT"||n.name=="Ask ChatGPT")),"普通 ChatGPT 输入框（不支持 Work/Codex）");
 }
 static string AppDraft(ANode input){string v=Value(input);return v=="询问 ChatGPT"||v=="Ask ChatGPT"?"":v;}
 static bool AppGenerating(ANode root){return All(root).Any(n=>n.role==43&&(n.name=="停止"||n.name=="Stop"||n.name=="停止生成"||n.name=="Stop generating"));}
 static void AppGuard(ANode root){AppInput(root);if(appTitle!=""&&AppName(root)!=appTitle)throw new Exception("普通聊天会话已切换；未执行输入或发送");}
 internal static bool AppModelPickerControl(ANode n){return (n.role==43||n.role==57)&&(n.name=="选择 ChatGPT 模型"||n.name=="Choose ChatGPT model"||n.name=="Select ChatGPT model");}
 static ANode AppPicker(ANode root){return Unique(All(root).Where(AppModelPickerControl),"普通聊天模型选择器");}
 static ANode AppWait(Func<ANode,bool> ready,int timeout=3500){var sw=Stopwatch.StartNew();while(sw.ElapsedMilliseconds<timeout){Pump();var root=AppRoot();if(ready(root))return root;Thread.Sleep(35);}throw new Exception("ChatGPT 应用控件更新超时");}
 static ANode CloseAppMenus(){var root=AppRoot();for(int i=0;i<3&&All(AppDoc(root)).Any(n=>n.role==11);i++){Front(chatApp);Press(0x1b);Thread.Sleep(50);Pump();root=AppRoot();}if(All(AppDoc(root)).Any(n=>n.role==11))throw new Exception("无法收起普通聊天菜单");return root;}
 internal static bool AppSelectModelControl(ANode n){return n.role==12&&(n.state&0x10000)==0&&(n.name=="选择模型"||n.name=="Select model");}
 internal static bool AppPickerReady(ANode root){return All(root).Any(n=>AppSelectModelControl(n)||n.role==12&&(n.state&0x10000)==0&&n.name.StartsWith("GPT-"));}
 internal static Match AppEffortPosition(string status){return Regex.Match(status,@"^.+(?:，第\s*(\d+)\s*项，共\s*(\d+)\s*项|,\s*(\d+)\s+of\s+(\d+))[。.]?$");}
 internal static int AppEffortIndex(string status){var m=AppEffortPosition(status);return !m.Success?0:Convert.ToInt32(m.Groups[1].Success?m.Groups[1].Value:m.Groups[3].Value);}
 internal static int AppEffortCount(string status){var m=AppEffortPosition(status);return !m.Success?0:Convert.ToInt32(m.Groups[2].Success?m.Groups[2].Value:m.Groups[4].Value);}
 internal static string AppEffortStatus(ANode root){return All(root).Where(n=>n.role==11&&(n.state&0x10000)==0).SelectMany(All).Where(n=>n.role==41&&AppEffortPosition(n.name).Success).Select(n=>n.name).Distinct().SingleOrDefault()??"";}
 internal static List<ANode> AppModelChoices(ANode root,string selectedModel){return All(root).Where(n=>n.role==12&&(n.state&0x10000)==0&&(n.name.StartsWith("GPT-")||n.name==selectedModel)).ToList();}
 static ANode OpenAppPicker(){var root=AppRoot();AppGuard(root);if(AppPickerReady(AppDoc(root)))return root;Click(AppPicker(root),chatApp);return AppWait(t=>AppPickerReady(AppDoc(t)));}
 static ANode EnsureChatMode(ANode root){
  Func<ANode,ANode> mode=t=>All(t).FirstOrDefault(n=>(n.role==43||n.role==57)&&(n.name.StartsWith("切换模式，当前模式：")||n.name.StartsWith("Switch mode, current mode:")));
  var current=mode(root);if(current==null||current.name.EndsWith("ChatGPT"))return root;
  appSettingsMemo.Clear();
  Click(current,chatApp);root=AppWait(t=>All(t).Any(n=>n.role==12&&n.name.StartsWith("ChatGPT ")));
  Click(Unique(All(root).Where(n=>n.role==12&&n.name.StartsWith("ChatGPT ")),"ChatGPT 普通聊天模式"),chatApp);
  return AppWait(t=>mode(t)!=null&&mode(t).name.EndsWith("ChatGPT"));
 }
 static ANode OpenAppConversation(string title){
  appTitle=title;var root=EnsureChatMode(AppRoot());
  if(title!=""&&AppName(root)!=title){
   appSettingsMemo.Clear();
   var target=Unique(All(root).Where(n=>n.role==43&&n.name==title&&(n.state&0x8000)==0),"侧边栏中的目标普通聊天");Click(target,chatApp);
   root=AppWait(t=>AppName(t)==title);
  }
  Func<ANode,bool> ready=t=>(title==""||AppName(t)==title)&&All(t).Any(n=>n.role==42&&(n.name=="询问 ChatGPT"||n.name=="Ask ChatGPT"));
  if(!ready(root))root=AppWait(ready,6000);AppGuard(root);return root;
 }
 internal class AppSettingsMemo {
  string title,model,effort;long window;uint process;public string ActualModel,ActualEffort;
  public bool Matches(string t,string m,string e,long w,uint p){return title!=null&&t!=""&&title==t&&model==m&&effort==e&&window==w&&process==p;}
  public void Clear(){title=null;ActualModel=ActualEffort=null;}
  public void Confirm(string t,string m,string e,long w,uint p,string actualModel,string actualEffort){title=t;model=m;effort=e;window=w;process=p;ActualModel=actualModel;ActualEffort=actualEffort;}
 }
 static readonly AppSettingsMemo appSettingsMemo=new AppSettingsMemo();
 static object PreparedApp(ANode root,string actualModel,string status,bool reused){
  var expand=AppPromptExpandButton(root);if(expand!=null){Click(expand,chatApp);Thread.Sleep(120);Pump();root=AppRoot();AppGuard(root);}
  MarkAppImages(root);MarkAppFiles(root);
  return new{ready=true,title=AppName(root),model=actualModel,effort=status,settingsReused=reused,tree=AppDoc(root),draft=AppDraft(AppInput(root)),attachments=AppAttachmentCount(root),idle=!AppGenerating(root)};
 }
 static object AppPrepare(string title,string selectedModel,string effort,bool forceSettings=false){
  var root=OpenAppConversation(title);
  appTitle=title;AppGuard(root);if(AppDraft(AppInput(root))!=""||AppAttachmentCount(root)!=0)throw new Exception("普通聊天存在人工文字或图片草稿，暂停以避免覆盖");expectedAppAttachments=0;ownedAppExpected=ownedAppCheckpoint=null;ownedAppAttachments.Clear();
  if(AppGenerating(root))throw new Exception("普通聊天正在生成其他回复，暂停以避免串话");
  uint process;GetWindowThreadProcessId(chatApp,out process);
  if(!forceSettings&&appSettingsMemo.Matches(title,selectedModel,effort,chatApp.ToInt64(),process))return PreparedApp(root,appSettingsMemo.ActualModel,appSettingsMemo.ActualEffort,true);
  // Invalidate before touching a menu; a partially failed selection is never cached.
  appSettingsMemo.Clear();
  if(!All(root).Any(AppModelPickerControl))root=AppWait(t=>All(t).Any(AppModelPickerControl),6000);
  root=OpenAppPicker();var select=All(root).FirstOrDefault(AppSelectModelControl);
  if(select!=null){Click(select,chatApp);root=AppWait(t=>AppModelChoices(t,selectedModel).Count>0);}
  var models=AppModelChoices(root,selectedModel);
  var chosen=selectedModel=="current"?Unique(models.Where(n=>(n.state&16)!=0),"当前普通聊天模型"):Unique(models.Where(n=>n.name==selectedModel),"指定的普通聊天模型");
  string actualModel=chosen.name;Click(chosen,chatApp);Thread.Sleep(60);CloseAppMenus();
  root=OpenAppPicker();
  Func<ANode,string> level=AppEffortStatus;
  string status=level(root);if(status=="")throw new Exception("无法核对普通聊天思考强度");
  if(effort!="current"){
   int desired=effort=="low"?1:effort=="medium"?2:effort=="high"?3:0;if(desired==0)throw new Exception("不支持的思考强度");
   if(AppEffortCount(status)!=3)throw new Exception("普通聊天的思考档位已变化，请重新检查适配");
   if(AppEffortIndex(status)!=desired){
    var strength=Unique(All(root).Where(n=>n.role==12&&(n.name=="强度"||n.name=="Power")&&(n.state&0x10000)==0),"思考强度控件");Click(strength,chatApp);
    for(int i=0;i<3;i++){Press(0x25);Thread.Sleep(25);Pump();}for(int i=1;i<desired;i++){Press(0x27);Thread.Sleep(25);Pump();}
    root=AppWait(t=>AppEffortIndex(level(t))==desired&&AppEffortCount(level(t))==3);status=level(root);
   }
  }
  root=CloseAppMenus();AppGuard(root);
  appSettingsMemo.Confirm(title,selectedModel,effort,chatApp.ToInt64(),process,actualModel,status);
  return PreparedApp(root,actualModel,status,false);
 }
 internal static ANode AppPromptExpandButton(ANode root){
  var region=All(root).FirstOrDefault(n=>(n.role==16||n.role==20)&&(n.name=="对话"||n.name=="Conversation"));if(region==null)return null;
  var heading=All(region).LastOrDefault(n=>n.role==20&&(n.name=="你说："||n.name=="You said:"));if(heading==null)return null;
  for(var scope=heading.parent;scope!=null;scope=scope.parent){
   int index=scope.children.FindIndex(n=>All(n).Any(x=>object.ReferenceEquals(x,heading)));if(index<0)continue;
   var segment=new List<ANode>();
   for(int i=index;i<scope.children.Count;i++){
    var branch=scope.children[i];if(i>index&&All(branch).Any(n=>n.role==20&&(n.name=="你说："||n.name=="You said:"||n.name=="ChatGPT 说："||n.name=="ChatGPT said:")))break;
    segment.AddRange(All(branch));
   }
   var buttons=segment.Where(n=>n.role==43&&(n.name=="显示更多"||n.name=="Show more")&&(n.state&0x18001)==0).ToList();
   if(buttons.Count==1)return buttons[0];
   if(scope.children.Count(n=>All(n).Any(x=>x.role==20&&(x.name=="你说："||x.name=="ChatGPT 说："||x.name=="You said:"||x.name=="ChatGPT said:")))>1)break;
  }
  return null;
 }
 static object AppState(){var root=AppRoot();AppGuard(root);var expand=AppPromptExpandButton(root);if(expand!=null){Click(expand,chatApp);Thread.Sleep(120);Pump();root=AppRoot();AppGuard(root);}MarkAppImages(root);MarkAppFiles(root);string draft=AppDraft(AppInput(root));return new{title=AppName(root),draft=draft,tree=AppDoc(root),attachments=AppAttachmentCount(root),idle=draft==""&&!AppGenerating(root)};}
 internal static bool AppReadyToSubmit(ANode root){var controls=All(AppComposer(root)).ToList();var sends=controls.Where(AppSendControl).ToList();return sends.Count==1&&(sends[0].state&1)==0&&!controls.Any(AppExpandPastedTextControl)&&!controls.Any(n=>n.role==48&&(n.state&64)==0);}
 internal static bool AppExpandPastedTextControl(ANode node){
  return node.role==43&&(node.state&0x18001)==0&&Regex.IsMatch(node.name,"^(在文本框中显示|Show in text box|Show in text field|Show in composer)$");
 }
 internal static ANode AppPastedTextExpandButton(ANode root){
  var controls=All(AppComposer(root)).Where(AppExpandPastedTextControl).ToList();
  if(controls.Count>1)throw new Exception("普通聊天存在多个折叠文本，无法确定本次粘贴内容；未展开或提交");
  return controls.Count==1?controls[0]:null;
 }
 static bool PasteAppText(ANode input,string text){
  var previous=Clipboard.GetDataObject();uint owned=0;
  try{
   Front(chatApp);Click(input,chatApp);
   Clipboard.SetText(text,TextDataFormat.UnicodeText);owned=GetClipboardSequenceNumber();
   Key(0x11,true);try{Press(0x56);}finally{Key(0x11,false);}
   bool expanded=false;
   AppWait(root=>{
    AppGuard(root);
    var expand=AppPastedTextExpandButton(root);
    // This client's MSAA default action can report success without expanding.
    // Click once, then require the complete original draft before allowing Send.
    if(!expanded&&expand!=null){expanded=true;Click(expand,chatApp);return false;}
    return AppDraft(AppInput(root))==text.Trim();
   },10000);
   return expanded;
  }finally{
   if(owned!=0&&GetClipboardSequenceNumber()==owned){
    if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();
   }
  }
 }
 static object AppFill(string text){var root=AppRoot();AppGuard(root);var input=AppInput(root);if(AppDraft(input)!="")throw new Exception("普通聊天存在人工草稿");ownedAppExpected=text;ownedAppCheckpoint="";commandDraftTouched=true;bool expanded;try{expanded=PasteAppText(input,text);}finally{RememberAppComposer();}return new{filled=true,pasteExpanded=expanded};}
 internal static bool AppSubmissionConfirmed(string draft,int attachments,bool latestMatches){return draft==""&&attachments==0&&latestMatches;}
 internal static ANode AppReplyCopyControl(ANode root,string expected){
  if(!LatestAppPromptMatches(root,expected))throw new Exception("复制回复对应的提问已变化，未复制");
  var region=AppConversation(root);var nodes=All(region).ToList();int user=nodes.FindLastIndex(n=>n.role==20&&(n.name=="你说："||n.name=="You said:"));
  int answer=nodes.FindIndex(user+1,n=>n.role==20&&(n.name=="ChatGPT 说："||n.name=="ChatGPT said:"));if(answer<0)throw new Exception("本次回复尚未出现");
  int end=nodes.FindIndex(answer+1,n=>n.role==20&&(n.name=="你说："||n.name=="You said:"||n.name=="ChatGPT 说："||n.name=="ChatGPT said:"));
  return Unique(nodes.Skip(answer+1).Take((end<0?nodes.Count:end)-answer-1).Where(n=>n.role==43&&Regex.IsMatch(n.name,"^(复制|复制回复|Copy|Copy response)$")&&(n.state&1)==0),"本次回复复制按钮");
 }
 static object CopyAppReply(string expected){
  var root=AppRoot();AppGuard(root);if(AppGenerating(root)||AppDraft(AppInput(root))!=""||AppAttachmentCount(root)!=0)throw new Exception("AI仍在生成或存在草稿，未复制未完成回复");
  var copy=AppReplyCopyControl(root,expected);var previous=Clipboard.GetDataObject();uint before=GetClipboardSequenceNumber(),owned=0;
  try{Invoke(copy,chatApp);var watch=Stopwatch.StartNew();while(watch.ElapsedMilliseconds<3000){Pump();if(GetClipboardSequenceNumber()!=before&&Clipboard.ContainsText(TextDataFormat.UnicodeText)){
    owned=GetClipboardSequenceNumber();string text=Clipboard.GetText(TextDataFormat.UnicodeText).Replace("\r\n","\n");
    root=AppRoot();AppGuard(root);if(!LatestAppPromptMatches(root,expected)||AppGenerating(root))throw new Exception("复制期间AI会话已变化，未使用剪贴板");
    if(string.IsNullOrWhiteSpace(text)||text.Length>150000)throw new Exception("回复源文字为空或超过大小限制");return new{text=text};
   }Thread.Sleep(30);}throw new Exception("未确认复制本次回复的Markdown原文，未发送混乱格式");
  }finally{if(owned!=0&&GetClipboardSequenceNumber()==owned){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}
 }
 static object AppSubmit(string expected){var root=AppRoot();AppGuard(root);if(AppDraft(AppInput(root))!=expected.Trim()||AppAttachmentCount(root)!=expectedAppAttachments)throw new Exception("普通聊天草稿或附件已变化，拒绝提交");root=AppWait(t=>{AppGuard(t);if(AppDraft(AppInput(t))!=expected.Trim()||AppAttachmentCount(t)!=expectedAppAttachments)throw new Exception("等待上传时草稿或附件已变化，未发送");return AppReadyToSubmit(t);},30000);var send=Unique(All(AppComposer(root)).Where(AppSendControl),"普通聊天发送按钮");commandCommitAttempted=true;Click(send,chatApp);bool expanded=false;try{AppWait(t=>{AppGuard(t);var expand=AppPromptExpandButton(t);if(!expanded&&expand!=null&&AppDraft(AppInput(t))=="" ){expanded=true;Click(expand,chatApp);return false;}return AppSubmissionConfirmed(AppDraft(AppInput(t)),AppAttachmentCount(t),LatestAppPromptMatches(t,expected));},8000);}catch(Exception e){throw new Exception("AI_SUBMIT_UNCERTAIN: 已尝试提交但尚未确认进入会话；先核查草稿和本条记录，未再次点击发送。 "+e.Message);}expectedAppAttachments=0;return new{submitted=true};}
 static ANode Address(ANode t){return Unique(All(t).Where(n=>n.role==42&&(n.name.Contains("地址和搜索栏")||n.name.Contains("Address and search bar"))),"Chrome 地址栏");}
 static string AddressURL(ANode a){string v=a.value.Trim();return v.Contains("://")?v:"https://"+v;}
 static ANode ChromeTree(){
  var candidates=new List<IntPtr>();foreach(var h in Windows("chrome")){try{var meta=Tree(h,true);if(Allowed(AddressURL(Address(meta))))candidates.Add(h);}catch{}}
  if(candidates.Count!=1)throw new Exception("请在 Chrome 中仅保留一个打开目标站点的窗口；当前可用窗口数："+candidates.Count);
  chrome=candidates[0];var root=Tree(chrome);var doc=Unique(All(root).Where(n=>n.role==15&&Allowed(n.value)),"OpenWebUI 页面");if(!Allowed(AddressURL(Address(root))))throw new Exception("Chrome 已离开允许域名，停止网页操作");cachedAddress=Address(root);cachedDocument=doc;cachedBrowserInput=BrowserInput(doc);return doc;
 }
 static ANode BrowserInput(ANode root){return Unique(All(root).Where(n=>n.role==20&&n.hasValue&&n.value.Length>0&&(n.state&0x100000)!=0&&(n.state&0x40)==0),"OpenWebUI 输入框");}
 static string Draft(ANode n){string v=Value(n);return v=="有什么我能帮您的吗？"||v=="输入消息"?"":v;}
 static void CheckModel(ANode doc){if(!All(doc).Any(n=>(n.role==57||n.role==43)&&n.name.Contains("已选择")&&n.name.Contains(model)))throw new Exception("网页模型不匹配，请在网页选择："+model);}
 static object BrowserState(){ANode doc=null;ANode input=null;if(cachedDocument!=null&&IsWindow(chrome)){string current=Value(cachedAddress);if(!current.Contains("://"))current="https://"+current;if(!Allowed(current))throw new Exception("Chrome 已离开允许域名，停止网页操作");try{string url=Value(cachedDocument);if(new Uri(current).AbsolutePath!=new Uri(url).AbsolutePath)throw new Exception("页面正在切换");budget=0;doc=Read(cachedDocument.acc,cachedDocument.childId,0,null,false,true);input=cachedBrowserInput;Value(input);}catch{doc=null;}}if(doc==null){doc=ChromeTree();input=BrowserInput(doc);}string draft=Draft(input);return new{url=doc.value,draft=draft,tree=doc,idle=draft==""&&All(doc).Any(n=>n.role==43&&(n.name=="语音模式"||n.name=="Voice mode")),modelMatched=All(doc).Any(n=>n.name.Contains("已选择")&&n.name.Contains(model))};}
 static object BrowserNavigate(string url){
  if(!Allowed(url))throw new Exception("拒绝导航到未允许的域名");var doc=ChromeTree();if(doc.value.TrimEnd('/')==url.TrimEnd('/'))return new{navigated=false};if(Draft(BrowserInput(doc))!="")throw new Exception("网页输入框存在人工草稿，暂停导航");
  var root=Tree(chrome,true);var address=Address(root);Front(chrome);Press(0x1b);Key(0x11,true);Press(0x4c);Key(0x11,false);Put(address,url,chrome);Press(0x0d);cachedDocument=null;cachedBrowserInput=null;return new{navigated=true};
 }
 static object BrowserFill(string text){var doc=ChromeTree();CheckModel(doc);var input=BrowserInput(doc);if(Draft(input)!="")throw new Exception("网页输入框存在草稿，暂停以避免覆盖");ownedBrowserExpected=text;ownedBrowserCheckpoint="";ownedBrowserUrl=doc.value;commandDraftTouched=true;try{Put(input,text,chrome);}finally{string actual=Draft(input);if(text.Trim().StartsWith(actual,StringComparison.Ordinal))ownedBrowserCheckpoint=actual;}return new{filled=true};}
 static object BrowserSubmit(string expected){var doc=ChromeTree();CheckModel(doc);var input=BrowserInput(doc);if(Draft(input)!=expected.Trim())throw new Exception("网页草稿已变化，拒绝提交");var buttons=All(doc).Where(n=>n.role==43&&(n.name=="send-message-button"||n.name=="发送消息")).ToList();if(buttons.Count==0){var scope=input.parent;while(scope!=null&&!All(scope).Any(n=>n.role==43&&n.name=="Voice Input"))scope=scope.parent;if(scope!=null)buttons=All(scope).Where(n=>n.role==43&&n.name=="").ToList();}var send=Unique(buttons,"网页发送按钮");if((send.state&1)!=0)throw new Exception("网页发送按钮不可用");commandCommitAttempted=true;Invoke(send,chrome);return new{submitted=true};}
}
