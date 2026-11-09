using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

partial class Bridge {
 static object CaptureQQQuotePreview(string reference){
  ImageSource source;if(!qqImageSources.TryGetValue(reference,out source))throw new Exception("QUOTE_UNAVAILABLE: 引用来源已过期");QQTree();budget=0;
  var row=Read(source.row.acc,source.row.childId,0,null,false,true);if(ImageFingerprint(row)!=source.fingerprint)throw new Exception("QUOTE_UNAVAILABLE: 引用提问已变化");
  var card=QQReplyCard(row);if(card==null)throw new Exception("QUOTE_UNAVAILABLE: 引用卡片不存在");var images=new List<object>();foreach(var image in All(card.children[2]).Where(n=>n.role==40))images.Add(CaptureQuotedPreview(image));return new{images=images};
 }
 static object CaptureQuotedPreview(ANode image){
  Front(qq);Pump();var rect=QuoteRect(image);if(rect.Width<2||rect.Height<2||rect.Width*(long)rect.Height>40000000)throw new Exception("QUOTE_UNAVAILABLE: 引用预览不可见或尺寸无效");
  foreach(var p in new[]{new POINT(rect.Left+1,rect.Top+1),new POINT(rect.Right-2,rect.Top+1),new POINT(rect.Left+1,rect.Bottom-2),new POINT(rect.Right-2,rect.Bottom-2)})if(GetAncestor(WindowFromPoint(p),2)!=qq)throw new Exception("QUOTE_UNAVAILABLE: 引用预览被遮挡");
  System.IO.Directory.CreateDirectory(MediaRoot);string path=System.IO.Path.Combine(MediaRoot,Guid.NewGuid().ToString("N")+".png");
  using(var bitmap=new Bitmap(rect.Width,rect.Height))using(var graphics=Graphics.FromImage(bitmap)){graphics.CopyFromScreen(rect.Location,Point.Empty,rect.Size);if(GetForegroundWindow()!=qq)throw new Exception("QUOTE_UNAVAILABLE: 引用预览读取时焦点变化");bitmap.Save(path,System.Drawing.Imaging.ImageFormat.Png);}
  return new{path=path,width=rect.Width,height=rect.Height,mime="image/png",quotedPreview=true};
 }
 internal static ANode QQAuthoredBody(ANode row,out string sender){
  sender="";var avatar=All(row).FirstOrDefault(n=>n.role==20&&n.name!=""&&n.children.Count>0&&!n.name.StartsWith("@")&&!System.Text.RegularExpressions.Regex.IsMatch(n.name,@"^\d{1,2}:\d{2}$"));
  if(avatar==null||avatar.parent==null)return null;var siblings=avatar.parent.children;int at=siblings.IndexOf(avatar);
  if(at+2>=siblings.Count||siblings[at+1].role!=20||siblings[at+2].role!=20)return null;
  var label=All(siblings[at+1]).FirstOrDefault(n=>n.role==41);if(label==null||label.name!=avatar.name)return null;sender=avatar.name;return siblings[at+2];
 }
 static string QuotePlain(string text){return System.Text.RegularExpressions.Regex.Replace(text??"",@"\s+","");}
 internal static bool QuoteSourceMatches(ANode row,ANode card){
  string sender;var body=QQAuthoredBody(row,out sender);if(body==null||sender!=card.children[0].name)return false;
  var nested=QQReplyCard(row);var skip=nested==null?new HashSet<ANode>():new HashSet<ANode>(All(nested));
  var authored=All(body).Where(n=>!skip.Contains(n)).ToList();var images=All(card.children[2]).Any(n=>n.role==40);
  if(images)return authored.Any(IsQQImage);
  var expected=QuotePlain(string.Join("\n",All(card.children[2]).Where(n=>n.role==41).Select(n=>n.name)));
  var actual=QuotePlain(string.Join("\n",authored.Where(n=>n.role==41).Select(n=>n.name)));
  if(expected.EndsWith("…"))expected=expected.TrimEnd('…');else if(expected.EndsWith("..."))expected=expected.Substring(0,expected.Length-3);
  return expected.Length>0&&actual.StartsWith(expected,StringComparison.Ordinal);
 }
 static Rectangle QuoteRect(ANode node){int x,y,w,h;node.acc.accLocation(out x,out y,out w,out h,node.childId);return new Rectangle(x,y,w,h);}
 static Bitmap QuotePanel(Rectangle bounds){
  if(bounds.Width<40||bounds.Height<20||bounds.Width*(long)bounds.Height>12000000)throw new Exception("QUOTE_UNAVAILABLE: 消息列表尺寸无效");
  for(int ix=0;ix<3;ix++)for(int iy=0;iy<3;iy++)if(GetAncestor(WindowFromPoint(new POINT(bounds.Left+2+(bounds.Width-5)*ix/2,bounds.Top+2+(bounds.Height-5)*iy/2)),2)!=qq)throw new Exception("QUOTE_UNAVAILABLE: 消息列表被遮挡");
  var bitmap=new Bitmap(bounds.Width,bounds.Height);try{using(var graphics=Graphics.FromImage(bitmap))graphics.CopyFromScreen(bounds.Location,Point.Empty,bounds.Size);if(GetForegroundWindow()!=qq)throw new Exception("QUOTE_UNAVAILABLE: 引用读取时焦点变化");return bitmap;}catch{bitmap.Dispose();throw;}
 }
 // A jump must produce a new, uniform highlight spanning both message-list
 // margins. Author/content checks alone cannot distinguish repeated images.
 internal static bool QuoteHighlight(Bitmap before,Bitmap after,Rectangle row){
  if(before.Size!=after.Size||row.Height<12||row.Top<0||row.Bottom>after.Height)return false;
  var reference=after.GetPixel(4,row.Top+row.Height/2);int hits=0;
  bool boundary=false;foreach(int y in new[]{row.Top-1,row.Bottom})if(y>=0&&y<after.Height){var color=after.GetPixel(4,y);if(Math.Max(Math.Abs(color.R-reference.R),Math.Max(Math.Abs(color.G-reference.G),Math.Abs(color.B-reference.B)))>=8)boundary=true;}
  if(!boundary)return false;
  foreach(int y in new[]{row.Top+row.Height/4,row.Top+row.Height/2,row.Top+row.Height*3/4})foreach(int x in new[]{4,after.Width-17}){
   var a=after.GetPixel(x,y);var b=before.GetPixel(x,y);
   if(Math.Abs(a.R-reference.R)<=3&&Math.Abs(a.G-reference.G)<=3&&Math.Abs(a.B-reference.B)<=3&&Math.Max(Math.Abs(a.R-b.R),Math.Max(Math.Abs(a.G-b.G),Math.Abs(a.B-b.B)))>=8)hits++;
  }
  return hits==6;
 }
 static string CopyQuotedOriginalText(ANode body){
  var previous=Clipboard.GetDataObject();uint owned=0;
  try{
   Clipboard.SetText("quote-original-"+Guid.NewGuid().ToString("N"));owned=GetClipboardSequenceNumber();RightClick(body,qq);
   ANode action=null;var until=DateTime.UtcNow.AddMilliseconds(1500);
   while(DateTime.UtcNow<until){Pump();var matches=ImageCopyMenuActions(Tree(qq,false,true),"复制");if(matches.Count==1){action=matches[0];break;}Thread.Sleep(35);}
   if(action==null)throw new Exception("QUOTE_UNAVAILABLE: 找不到原消息复制菜单");Click(action,qq);
   until=DateTime.UtcNow.AddMilliseconds(1500);
   while(DateTime.UtcNow<until){Pump();if(GetClipboardSequenceNumber()!=owned&&Clipboard.ContainsText()){owned=GetClipboardSequenceNumber();var text=Clipboard.GetText().Replace("\r\n","\n").Trim();if(text.Length>200000)throw new Exception("QUOTE_UNAVAILABLE: 原文过长，未截断冒充全文");return text;}Thread.Sleep(30);}
   throw new Exception("QUOTE_UNAVAILABLE: 未取得原消息文字");
  }finally{try{if(GetForegroundWindow()==qq)Press(0x1b);if(GetClipboardSequenceNumber()==owned){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}catch{}}
 }
 static void QuoteReturnLatest(string anchor){
  if(cachedQQHeader.acc.get_accName(cachedQQHeader.childId)!=group)throw new Exception("QUOTE_VIEW_RESTORE_FAILED: 群会话已变化，未滚动其他群");
  var list=QuoteRect(cachedQQList);var point=new POINT(list.Left+list.Width/2,list.Top+list.Height/2);
  if(GetForegroundWindow()!=qq||GetAncestor(WindowFromPoint(point),2)!=qq)throw new Exception("QUOTE_VIEW_RESTORE_FAILED: 窗口已变化，未滚动其他窗口");
  SetCursorPos(point.x,point.y);var wheel=new INPUT{type=0,u=new UNION{mi=new MOUSE{flags=0x0800,data=unchecked((uint)-120000)}}};
  if(SendInput(1,new[]{wheel},Marshal.SizeOf(typeof(INPUT)))!=1)throw new Exception("QUOTE_VIEW_RESTORE_FAILED: 无法回到最新消息");Thread.Sleep(100);Pump();
  if(cachedQQHeader.acc.get_accName(cachedQQHeader.childId)!=group)throw new Exception("群会话已变化");
  var rows=QQRows(ReadMessages());if(!rows.Any(r=>ImageFingerprint(r)==anchor&&QuoteRect(r).IntersectsWith(list)))throw new Exception("QUOTE_VIEW_RESTORE_FAILED: 尚未确认回到最新消息，未继续监听旧记录");
 }
 static object ResolveQQQuote(string reference,bool forwardImages,int maxImages){
  ImageSource source;if(!qqImageSources.TryGetValue(reference,out source))throw new Exception("QUOTE_UNAVAILABLE: 引用来源已过期");
  QQTree();budget=0;var current=Read(source.row.acc,source.row.childId,0,null,false,true);
  if(ImageFingerprint(current)!=source.fingerprint)throw new Exception("QUOTE_UNAVAILABLE: 引用提问已变化");
  var card=QQReplyCard(current);if(card==null)throw new Exception("QUOTE_UNAVAILABLE: 引用卡片不存在");Front(qq);
  var bounds=QuoteRect(cachedQQList);var origin=QuoteRect(card);if(!bounds.Contains(origin))throw new Exception("QUOTE_UNAVAILABLE: 引用卡片不在可见区域");
  var rowsBefore=QQRows(ReadMessages());string anchor=ImageFingerprint(rowsBefore.Last());bool jumped=false;
  try{using(var before=QuotePanel(bounds)){
   var point=QuoteRect(card.children[1]);if(!bounds.Contains(point))throw new Exception("QUOTE_UNAVAILABLE: 引用跳转入口不可见");
   jumped=true;Click(card.children[1],qq);Thread.Sleep(90);Pump();
   ANode original=null;var until=DateTime.UtcNow.AddMilliseconds(950);
   while(DateTime.UtcNow<until){
    var rows=QQRows(ReadMessages());using(var after=QuotePanel(bounds)){
     var candidates=rows.Where(r=>{var rect=QuoteRect(r);return rect.Height>0&&bounds.Contains(rect)&&QuoteSourceMatches(r,card)&&QuoteHighlight(before,after,new Rectangle(0,rect.Top-bounds.Top,bounds.Width,rect.Height));}).ToList();
     if(candidates.Count>1)throw new Exception("QUOTE_UNAVAILABLE: 原消息高亮不唯一");if(candidates.Count==1){original=candidates[0];break;}
    }Thread.Sleep(45);Pump();
   }
   if(original==null)throw new Exception("QUOTE_UNAVAILABLE: 未确认引用跳转后的原消息高亮");
   string sender;var body=QQAuthoredBody(original,out sender);var nested=QQReplyCard(original);var excluded=nested==null?new HashSet<ANode>():new HashSet<ANode>(All(nested));
   var images=All(body).Where(n=>!excluded.Contains(n)&&IsQQImage(n)).ToList();var saved=new List<object>();string text="";
   if(images.Count==0){text=CopyQuotedOriginalText(body);var expected=QuotePlain(string.Join("\n",All(card.children[2]).Where(n=>n.role==41).Select(n=>n.name))).TrimEnd('…');if(expected.EndsWith("..."))expected=expected.Substring(0,expected.Length-3);if(QuotePlain(text).Length==0||!QuotePlain(text).StartsWith(expected,StringComparison.Ordinal))throw new Exception("QUOTE_UNAVAILABLE: 复制原文与引用内容不匹配");}
   else{
    text=string.Join("\n",All(body).Where(n=>!excluded.Contains(n)&&n.role==41).Select(n=>n.name));
    if(forwardImages){if(images.Count>Math.Min(4,maxImages))throw new Exception("QUOTE_UNAVAILABLE: 引用原图数量超过限制");foreach(var image in images){try{saved.Add(CaptureContextImage(image,qq,"复制"));}catch(Exception error){throw new Exception("QUOTE_UNAVAILABLE: 原图复制失败；"+error.Message);}}}
   }
   return new{sender=sender,text=text,imageCount=images.Count,images=saved,original=true};
  }}finally{if(jumped)QuoteReturnLatest(anchor);}
 }
}
