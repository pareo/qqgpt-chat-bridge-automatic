// QQ session discovery and name-based source-group routing. No network or QQ injection.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using System.Diagnostics;

partial class Bridge {
 internal class QQSession {
  public string groupName,signature,timeLabel;
  public int unread;
  public bool mentioned;
  [System.Web.Script.Serialization.ScriptIgnore] public ANode node;
 }
 internal static List<QQSession> SessionRows(ANode root){
  var list=Unique(All(root).Where(n=>n.name=="会话列表"),"QQ会话列表");
  var rows=new List<QQSession>();
  foreach(var row in list.children){
   // The name is made of direct text children of the title/preview container;
   // emoji may split it into several text leaves. Preview text is nested.
   var title=All(row).FirstOrDefault(n=>n.children.Any(c=>c.role==41)&&n.children.Any(c=>c.role==20));
   if(title==null)continue;
   string name=string.Concat(title.children.Where(n=>n.role==41).Select(n=>n.name));
   if(name=="")continue;
   var nodes=All(row).ToList();int unread=0;
   foreach(var n in nodes){var m=Regex.Match(n.name,@"^(\d+)条未读$");int value;if(m.Success&&int.TryParse(m.Groups[1].Value,out value))unread=Math.Max(unread,value);if(m.Success)foreach(var text in All(n).Where(t=>t.role==41)){int badge;if(int.TryParse(text.name,out badge))unread=Math.Max(unread,badge);}}
   rows.Add(new QQSession{groupName=name,timeLabel=string.Concat(All(title.children.FirstOrDefault(c=>c.role==20)??new ANode()).Where(n=>n.role==41).Select(n=>n.name)),unread=unread,mentioned=nodes.Any(n=>n.name=="有人@我"||n.name=="[有人@我]"),signature=string.Join("\u001f",nodes.Where(n=>n.name!="").Select(n=>n.name)),node=row});
  }
  return rows;
 }
 static object QQSessions(){var root=QQWindowTree();var header=CurrentGroupHeader(root);return new{sessions=SessionRows(root),currentGroupName=header==null?null:header.name};}
 internal static ANode CurrentGroupHeader(ANode root){
  // Private chats do not have the group toolbar. Never promote a private-chat
  // title or a sender's nickname to a group identity.
  if(!All(root).Any(n=>n.role==43&&(n.name=="群应用"||n.name=="邀请加群")))return null;
  var headers=All(root).Where(n=>n.role==43&&n.name!=""&&n.children.Any(c=>c.role==41&&Regex.IsMatch(c.name,@"^[（(]\d+[)）]$"))).ToList();
  return headers.Count==1?headers[0]:null;
 }
 internal static ANode RequireGroupName(ANode root,string name){
  var header=CurrentGroupHeader(root);
  if(string.IsNullOrWhiteSpace(name)||header==null||header.name!=name)throw new Exception("当前 QQ 聊天不是目标群："+name);
  if(SessionRows(root).Count(s=>s.groupName==name)!=1)throw new Exception("目标群会话重名或不可见，未路由："+name);
  return header;
 }
 static void SetQQBinding(string name,string id){
  if(name==group&&id==groupId)return;
  if(qqCommitPending)throw new Exception("SEND_UNCERTAIN: 原群发送结果尚未确认，禁止切换绑定");
  group=name;groupId=id;cachedQQHeader=cachedQQList=cachedQQInput=null;
  ownedQQExpected=ownedQQCheckpoint=null;NativeDraftNames.Clear();qqAttemptText=null;qqAttemptBefore=-1;
  recoveryQQImagePath=recoveryQQImageDraft=null;stagedQQFile=null;stagedQQFileBefore=-1;qqImageSources.Clear();
 }
 static object QQDiscoverCurrent(){
  var root=QQWindowTree();var header=CurrentGroupHeader(root);if(header==null)return new{isGroup=false};
  string name=header.name,id=name==group?groupId:"";RequireGroupName(root,name);SetQQBinding(name,id);BindQQTree(root);
  return new{isGroup=true,groupName=name,groupId=id};
 }
 static object QQOpenGroup(string name,string expectedId){
  if(string.IsNullOrWhiteSpace(name))throw new Exception("目标群信息无效");
  var root=QQWindowTree();var header=CurrentGroupHeader(root);
  if(header==null||header.name!=name){
   if(qqCommitPending)throw new Exception("SEND_UNCERTAIN: 发送确认前不能切换群");
   var candidates=SessionRows(root).Where(s=>s.groupName==name).ToList();if(candidates.Count!=1)throw new Exception("目标群会话重名或已不在会话列表，未切换："+name);
   Click(candidates[0].node,qq);
   var sw=Stopwatch.StartNew();do{Thread.Sleep(45);Pump();root=QQWindowTree();header=CurrentGroupHeader(root);if(header!=null&&header.name==name)break;}while(sw.ElapsedMilliseconds<2500);
   if(header==null||header.name!=name)throw new Exception("目标不是可验证的群聊，已跳过："+name);
  }
  RequireGroupName(root,name);
  // Keep a configured number only as optional saved metadata. Never read or compare it.
  string id=expectedId!=""?expectedId:name==group?groupId:"";
  SetQQBinding(name,id);BindQQTree(root);return new{isGroup=true,groupName=name,groupId=id};
 }
}
