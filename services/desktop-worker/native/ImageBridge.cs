using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

partial class Bridge {
 [DllImport("user32.dll")] static extern uint GetClipboardSequenceNumber();
 class ImageSource {public ANode row;public string fingerprint;public List<ANode> images;}
 static readonly Dictionary<string,ImageSource> qqImageSources=new Dictionary<string,ImageSource>();
 internal class AppImageSource {public string name,binding;public int ordinal,count;}
 static readonly Dictionary<string,AppImageSource> appImageSources=new Dictionary<string,AppImageSource>();
 static string MediaRoot {get{return Path.Combine(WorkerStateRoot,"media");}}
 static bool IsQQImage(ANode n){return n.role==40&&n.name=="图片";}
 internal static ANode QQReplyCard(ANode row){
  var sender=All(row).FirstOrDefault(n=>n.role==20&&n.name!=""&&n.children.Count>0&&!n.name.StartsWith("@")&&!Regex.IsMatch(n.name,@"^\d{1,2}:\d{2}$"));if(sender==null||sender.parent==null)return null;
  var siblings=sender.parent.children;int at=siblings.IndexOf(sender);if(at<0||at+2>=siblings.Count||siblings[at+1].role!=20||All(siblings[at+1]).FirstOrDefault(n=>n.role==41)==null||All(siblings[at+1]).First(n=>n.role==41).name!=sender.name)return null;
  var content=siblings[at+2];for(int i=0;content.children.Count==1&&i<8;i++)content=content.children[0];if(content.children.Count<2)return null;
  var card=content.children[0];var p=card.children;return card.role==20&&p.Count==3&&p[0].role==41&&p[0].name!=""&&p[1].role==40&&p[1].name==""&&(p[2].role==20||p[2].role==41)?card:null;
 }
 internal static List<ANode> QQMessageImages(ANode row){var card=QQReplyCard(row);var quoted=card==null?new List<ANode>():All(card.children[2]).Where(n=>n.role==40).ToList();return quoted.Concat(All(row).Where(IsQQImage)).Distinct().ToList();}
 static string ImageFingerprint(ANode row){return string.Join("|",All(row).Where(n=>n.role==41&&!Regex.IsMatch(n.name.Trim(),@"^(?:(?:今天|昨天|\d{1,2}月\d{1,2}日|\d{1,2}-\d{1,2})\s*)?\d{1,2}:\d{2}(?::\d{2})?$" )).Select(n=>n.name))+"#"+QQMessageImages(row).Count;}
 static void MarkQQImages(List<ANode> rows){
  qqImageSources.Clear();foreach(var row in rows){var images=QQMessageImages(row);if(images.Count==0&&QQReplyCard(row)==null)continue;row.mediaRef=Guid.NewGuid().ToString("N");qqImageSources[row.mediaRef]=new ImageSource{row=row,images=images,fingerprint=ImageFingerprint(row)};}
 }
 static void RightClick(ANode n,IntPtr window){
  Front(window);int x,y,w,h;n.acc.accLocation(out x,out y,out w,out h,n.childId);if(w<1||h<1)throw new Exception("图片当前不可见，未复制");var p=new POINT(x+w/2,y+h/2);SetCursorPos(p.x,p.y);Thread.Sleep(40);
  if(GetForegroundWindow()!=window||GetAncestor(WindowFromPoint(p),2)!=window)throw new Exception("图片被其他窗口遮挡，未复制");
  var down=new INPUT{type=0,u=new UNION{mi=new MOUSE{flags=8}}};var up=new INPUT{type=0,u=new UNION{mi=new MOUSE{flags=16}}};SendInput(1,new[]{down},Marshal.SizeOf(typeof(INPUT)));Thread.Sleep(35);SendInput(1,new[]{up},Marshal.SizeOf(typeof(INPUT)));
 }
 internal static List<ANode> ImageCopyMenuActions(ANode root,string copyName){return All(root).Where(n=>n.role==12&&(n.state&0x18001)==0&&copyName.Split('|').Contains(n.name.Trim(),StringComparer.OrdinalIgnoreCase)).ToList();}
 static object CaptureContextImage(ANode image,IntPtr window,string copyName){
  Directory.CreateDirectory(MediaRoot);var previous=Clipboard.GetDataObject();uint owned=0;
  try{
   Clipboard.SetText("qq-bridge-copy-"+Guid.NewGuid().ToString("N"));owned=GetClipboardSequenceNumber();RightClick(image,window);
   ANode action=null;var sw=Stopwatch.StartNew();while(sw.ElapsedMilliseconds<2500){Pump();var root=Tree(window,false,window==qq);var matches=ImageCopyMenuActions(root,copyName);if(matches.Count==1){action=matches[0];break;}Thread.Sleep(40);}
   if(action==null){
    try{File.WriteAllText(Path.Combine(Directory.GetParent(MediaRoot).FullName,"image-copy-menu.private.json"),Json.Serialize(new{image=image.name,tree=Tree(window,false,window==qq)}));}catch{}
    throw new Exception("找不到图片复制菜单，未上传图片");
   }Click(action,window);
   sw.Restart();while(sw.ElapsedMilliseconds<4000){Thread.Sleep(40);Pump();if(GetClipboardSequenceNumber()==owned)continue;if(!Clipboard.ContainsImage())continue;owned=GetClipboardSequenceNumber();using(var bitmap=Clipboard.GetImage()){
    if(bitmap==null||bitmap.Width*(long)bitmap.Height>40000000)throw new Exception("图片为空或像素过大");string path=Path.Combine(MediaRoot,Guid.NewGuid().ToString("N")+".png");bitmap.Save(path,ImageFormat.Png);if(new FileInfo(path).Length>20971520)throw new Exception("图片超过20MB限制");return new{path=path,width=bitmap.Width,height=bitmap.Height,mime="image/png"};
   }}throw new Exception("未提供可读取的图片剪贴板，未复制旧图片");
  }finally{try{if(GetForegroundWindow()==window)Press(0x1b);if(GetClipboardSequenceNumber()==owned){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}catch{}}
 }
 static object CaptureQQImages(string reference){
  ImageSource source;if(!qqImageSources.TryGetValue(reference,out source))throw new Exception("图片消息引用已过期，需要重新读取");
  QQTree();budget=0;var current=Read(source.row.acc,source.row.childId,0,null,false,true);if(ImageFingerprint(current)!=source.fingerprint)throw new Exception("图片来源消息已变化，拒绝复制");
  var card=QQReplyCard(current);var excluded=card==null?new HashSet<ANode>():new HashSet<ANode>(All(card));var images=All(current).Where(n=>!excluded.Contains(n)&&IsQQImage(n)).ToList();if(images.Count>4)throw new Exception("一条消息最多转发4张图片");var saved=new List<object>();foreach(var image in images)saved.Add(CaptureContextImage(image,qq,"复制"));return new{images=saved};
 }
 static string LocalImage(string path){
  string full=Path.GetFullPath(path),prefix=Path.GetFullPath(MediaRoot)+Path.DirectorySeparatorChar;
  if(!full.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)||Path.GetExtension(full).ToLowerInvariant()!=".png"||!File.Exists(full)||new FileInfo(full).Length>20971520)throw new Exception("图片必须来自程序 state/media 内的有效PNG文件");return full;
 }
 static void PasteLocalImage(ANode input,IntPtr window,string path){
  path=LocalImage(path);Front(window);Click(input,window);Thread.Sleep(60);Pump();var previous=Clipboard.GetDataObject();uint owned=0;
  try{
   using(var source=Image.FromFile(path)){if(source.Width*(long)source.Height>40000000)throw new Exception("图片像素过大");using(var image=new Bitmap(source))Clipboard.SetImage(image);}
   owned=GetClipboardSequenceNumber();if(GetForegroundWindow()!=window)throw new Exception("粘贴图片前窗口焦点已变化");Key(0x11,true);try{Press(0x56);}finally{Key(0x11,false);}Thread.Sleep(350);Pump();
  }finally{try{if(GetClipboardSequenceNumber()==owned){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}catch{}}
 }
 internal static bool AppAddFilesControl(ANode n){return (n.role==43||n.role==57)&&(n.name=="添加文件等内容"||n.name=="添加文件及更多内容"||n.name=="添加照片和文件"||n.name=="Add photos & files"||n.name=="Add files and more");}
 internal static bool AppSendControl(ANode n){return n.role==43&&Regex.IsMatch(n.name,"^(发送|发送消息|发送提示词|Send|Send message|Send prompt)$");}
 internal static bool AppRemoveAttachmentControl(ANode n){return n.role==43&&(n.name.StartsWith("移除“")||n.name.StartsWith("移除 \"")||n.name.StartsWith("移除 ")||n.name.StartsWith("Remove "));}
 internal static ANode AppComposer(ANode root){
  var input=AppInput(root);ANode candidate=null;
  for(var node=input.parent;node!=null;node=node.parent){
   // Attachment chips can be a sibling of the inner editor row. Include the
   // complete composer branch, but never climb into history, sidebar or Work.
   var nodes=All(node).ToList();
   if(node.role==15||nodes.Any(n=>(n.role==16||n.role==20)&&(n.name=="对话"||n.name=="Conversation"||n.name=="Home"||n.name=="首页"))||nodes.Any(n=>n.role==42&&(n.name=="Work with ChatGPT"||n.name=="与 ChatGPT 协作")))break;
   if(nodes.Count(n=>n.role==42&&(n.name=="询问 ChatGPT"||n.name=="Ask ChatGPT"))!=1)break;
   if(nodes.Any(AppAddFilesControl)||nodes.Any(AppModelPickerControl)&&nodes.Any(AppSendControl))candidate=node;
  }
  if(candidate==null)throw new Exception("找不到普通聊天附件区域");return candidate;
 }
 internal static int AppAttachmentCount(ANode root){return All(AppComposer(root)).Count(AppRemoveAttachmentControl);}
 static int expectedAppAttachments;
 static ANode AppConversation(ANode root){return All(root).FirstOrDefault(n=>(n.role==16||n.role==20)&&(n.name=="对话"||n.name=="Conversation"));}
 internal static string AppImageBinding(ANode region){
  var nodes=All(region).ToList();int start=nodes.FindLastIndex(n=>n.role==20&&(n.name=="你说："||n.name=="You said:"));if(start<0)return "";
  int end=nodes.FindIndex(start+1,n=>n.role==20&&(n.name=="ChatGPT 说："||n.name=="ChatGPT said:"));
  return string.Join("\n",nodes.Skip(start).Take((end<0?nodes.Count:end)-start).Where(n=>n.role==41).Select(n=>n.name));
 }
 static void MarkAppImages(ANode root){
  appImageSources.Clear();var region=AppConversation(root);if(region==null)return;string binding=AppImageBinding(region);
  var images=All(region).Where(n=>n.role==40&&n.name.Length>0).ToList();
  foreach(var group in images.GroupBy(n=>n.name)){
   int ordinal=0;foreach(var image in group){image.mediaRef=Guid.NewGuid().ToString("N");appImageSources[image.mediaRef]=new AppImageSource{name=image.name,binding=binding,ordinal=ordinal++,count=group.Count()};}
  }
 }
 internal static ANode ResolveAppImage(ANode root,AppImageSource source){
  var region=AppConversation(root);if(region==null||AppImageBinding(region)!=source.binding)throw new Exception("图片对应的提问已变化，未复制其他回复");
  var matches=All(region).Where(n=>n.role==40&&n.name==source.name).ToList();
  if(matches.Count!=source.count||source.ordinal>=matches.Count)throw new Exception("回复图片列表已变化，需要重新读取");
  return matches[source.ordinal];
 }
 internal static ANode AppImageFocusTarget(ANode image){
  var target=image;while(target!=null&&target.role!=43)target=target.parent;
  if(target!=null)return target;
  // Search cards expose a graphic and a sibling Open button, rather than
  // placing the graphic inside a focusable generated-image button.
  if(image.parent==null)return null;
  var matches=All(image.parent).Where(n=>n.role==43&&n.name=="Open "+image.name).ToList();
  return matches.Count==1?matches[0]:null;
 }
 static void FocusAppImage(ANode image){
  // Chromium's accessibility focus brings the image button into the viewport.
  // Focus only; do not invoke the button, which opens an editing/lightbox UI.
  var target=AppImageFocusTarget(image);
  if(target==null)return;
  Front(chatApp);try{target.acc.accSelect(1,target.childId);Thread.Sleep(120);Pump();}catch(COMException){}
 }
 static object CaptureSearchAppImage(ANode source,ANode target){
  Click(target,chatApp);Thread.Sleep(250);Pump();
  try{
   var root=AppRoot();
   if(appTitle!=""&&AppName(root)!=appTitle)throw new Exception("图片预览已离开目标会话，未复制");
   var dialogs=All(root).Where(n=>n.role==18).ToList();
   var images=dialogs.SelectMany(All).Where(n=>n.role==40&&n.name==source.name).ToList();
   if(images.Count!=1)throw new Exception("联网图片预览未提供唯一原图，未复制其他内容");
   return CaptureContextImage(images[0],chatApp,"复制图像|复制图片|Copy image");
  }finally{if(GetForegroundWindow()==chatApp){Press(0x1b);Thread.Sleep(80);Pump();}}
 }
 static object CaptureAppImages(string[] references){AppGuard(AppRoot());var saved=new List<object>();if(references.Length>4)throw new Exception("回复图片超过4张");foreach(string reference in references){var root=AppWait(t=>All(t).Any(n=>n.role==42&&(n.name=="询问 ChatGPT"||n.name=="Ask ChatGPT")));AppGuard(root);AppImageSource descriptor;if(!appImageSources.TryGetValue(reference,out descriptor))throw new Exception("回复图片引用已过期");var source=ResolveAppImage(root,descriptor);FocusAppImage(source);var target=AppImageFocusTarget(source);saved.Add(target!=null&&target.name=="Open "+source.name?CaptureSearchAppImage(source,target):CaptureContextImage(source,chatApp,"复制图像|复制图片|Copy image"));}return new{images=saved};}
 static string pendingAppImage=null;static int pendingAppImageBefore=0;
 static object ConfirmAppAttachment(string path){var root=AppRoot();AppGuard(root);int count=AppAttachmentCount(root);bool confirmed=pendingAppImage==path&&count==pendingAppImageBefore+1&&!All(AppComposer(root)).Any(n=>n.role==48&&(n.state&64)==0);if(confirmed){expectedAppAttachments=count;pendingAppImage=null;}return new{confirmed=confirmed,count=count};}
 static object AttachAppImage(string path){
  var root=AppRoot();AppGuard(root);if(AppGenerating(root)||AppAttachmentCount(root)!=expectedAppAttachments)throw new Exception("普通聊天生成中或存在未绑定的人工附件，未附图");
  int before=expectedAppAttachments;pendingAppImage=path;pendingAppImageBefore=before;commandDraftTouched=true;try{PasteLocalImage(AppInput(root),chatApp,path);}finally{RememberAppComposer(true);}
  try{root=AppWait(t=>AppAttachmentCount(t)==before+1&&!All(AppComposer(t)).Any(n=>n.role==48&&(n.state&64)==0)&&All(AppComposer(t)).Any(n=>AppSendControl(n)&&(n.state&1)==0),15000);}finally{RememberAppComposer(true);}
  expectedAppAttachments=before+1;RememberAppComposer(true);pendingAppImage=null;return new{attached=true,count=expectedAppAttachments,title=AppName(root)};
 }
 static object StageQQImage(string path){var root=VerifyGroup();var input=QQInput(root);if(Value(input)!=""||All(input).Any(IsQQImage))throw new Exception("QQ 已有人工文字或图片草稿");PasteLocalImage(input,qq,path);Thread.Sleep(250);Pump();return new{staged=true,tree=QQTree()};}
 static int OwnImageCount(List<ANode> rows){return rows.Where(r=>{var sender=All(r).FirstOrDefault(n=>n.role==20&&n.name.Length>0&&n.children.Count>0&&!n.name.StartsWith("@"));return sender!=null&&sender.name==selfNickname;}).Sum(r=>All(r).Count(IsQQImage));}
 static void SendQQKey(){commandCommitAttempted=true;qqCommitPending=true;bool ctrl=sendShortcut=="ctrl-enter";if(ctrl)Key(0x11,true);try{Key(0x0d,true);Thread.Sleep(35);Key(0x0d,false);}catch(Exception e){throw new Exception("SEND_UNCERTAIN: 发送按键未完成："+e.Message);}finally{if(ctrl)Key(0x11,false);}}
 static object SendQQImage(string path){
  path=LocalImage(path);var root=VerifyGroup();var input=QQInput(root);if(Value(input)!=""||All(input).Any(IsQQImage))throw new Exception("QQ 存在人工草稿，未粘贴图片");
  int before=OwnImageCount(QQRows(ReadMessages()));ownedQQExpected=ownedQQCheckpoint=null;qqCommitPending=false;recoveryQQImagePath=path;recoveryQQImageDraft=null;commandDraftTouched=true;try{PasteLocalImage(input,qq,path);}finally{RememberQQRecoveryImage();}
  root=QQTree();input=QQInput(root);string draft=Value(input);if(draft.Length==0||!Regex.IsMatch(draft,@"^[\s\u200b-\u200f\u2060\ufeff]+$"))throw new Exception("QQ 图片草稿未就绪或含其他文字，未发送");
  var send=Unique(All(root).Where(n=>n.role==43&&n.name=="发送"),"QQ 发送按钮");if((send.state&1)!=0)throw new Exception("QQ 图片未就绪，未发送");FocusQQInput(input);
  if(GetForegroundWindow()!=qq||Value(input)!=draft)throw new Exception("QQ 图片草稿或焦点已变化，未发送");SendQQKey();
  var sw=Stopwatch.StartNew();while(sw.ElapsedMilliseconds<5000){Thread.Sleep(50);Pump();if(cachedQQHeader.acc.get_accName(cachedQQHeader.childId)!=group)throw new Exception("SEND_UNCERTAIN: 图片发送确认时群会话已变化");if(Value(input)==""&&OwnImageCount(QQRows(ReadMessages()))>before){qqCommitPending=false;recoveryQQImagePath=recoveryQQImageDraft=null;return new{sent=true,confirmed=true,kind="image"};}}
  throw new Exception("SEND_UNCERTAIN: 图片已尝试发送但未回读到自己新增图片，禁止自动重发");
 }
}
