using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

partial class Bridge {
 static bool nativeMentions=true;
 static string ownedQQExpected=null,ownedQQCheckpoint=null;
 static bool qqCommitPending=false;
 static string qqAttemptText=null;static int qqAttemptBefore=-1;
 internal static bool QQSendAdvanced(int before,int after,string draft){return before>=0&&after>before&&draft=="";}
 internal static bool QQOwnedDraftMatches(string draft,string expected,string checkpoint,bool committed,bool hasImage){return !hasImage&&(draft==""||!committed&&expected!=null&&(draft==checkpoint||QQTextMatches(draft,expected)));}
 static object ConfirmQQText(string text){VerifyGroup();bool confirmed=qqAttemptText==text&&QQSendAdvanced(qqAttemptBefore,ReplyCount(QQRows(ReadMessages()),text),Value(cachedQQInput));if(confirmed)qqCommitPending=false;return new{confirmed=confirmed};}
 static object ConfirmQQDraft(string text){var proof=VerifyGroup();var input=QQInput(proof);var previous=NativeDraftNames;var actual=DraftMentionLabels(input).Select(n=>n.Substring(1)).ToList();var plan=nativeMentions?MentionPlan(text,QQMemberNames(proof).Concat(CachedMemberNames()).Concat(actual)).Where(p=>p.name!=null).Select(p=>p.name):Enumerable.Empty<string>();bool allowed=OptionalMentionNamesMatch(actual,plan);NativeDraftNames=actual;bool confirmed=allowed&&QQTextMatches(Value(input),text);if(!confirmed)NativeDraftNames=previous;return new{confirmed=confirmed,nativeMentions=actual.ToArray()};}
 static void BeginOwnedQQDraft(string expected){ownedQQExpected=expected;ownedQQCheckpoint="";qqCommitPending=false;}
 static void RememberOwnedQQDraft(){if(ownedQQExpected!=null)ownedQQCheckpoint=QQReadStable(()=>Value(cachedQQInput));}
 static bool ResetOwnedQQDraft(){
  var input=QQInput(VerifyGroup());string draft=Value(input);
  if(draft==""&&!All(input).Any(IsQQImage)){ownedQQExpected=ownedQQCheckpoint=null;return true;}
  if(!QQOwnedDraftMatches(draft,ownedQQExpected,ownedQQCheckpoint,qqCommitPending,All(input).Any(IsQQImage)))return false;
  string directory=Path.GetDirectoryName(MemberCachePath);Directory.CreateDirectory(directory);
  File.WriteAllText(Path.Combine(directory,"failed-draft-"+Guid.NewGuid().ToString("N")+".private.json"),Json.Serialize(new{groupId=groupId,draft=draft,expected=ownedQQExpected,time=DateTime.UtcNow.ToString("o")}));
  PutQQ(input,"");ownedQQExpected=ownedQQCheckpoint=null;NativeDraftNames.Clear();return true;
 }
 static object SendQQError(string text){
  if(!ResetOwnedQQDraft())throw new Exception("QQ 有未确认的人工或图片草稿，错误通知保留在控制台，未覆盖草稿");
  bool previous=nativeMentions;try{nativeMentions=false;return QQSend(text,false);}finally{nativeMentions=previous;}
 }
 internal class MentionPart {public string text;public string name;public bool commandTail;public MentionPart(string t,string n=null,bool rawCommand=false){text=t;name=n;commandTail=rawCommand;}}
 static string MemberCachePath {get{return Path.Combine(WorkerStateRoot,"mention-members.json");}}
 internal static List<string> NativeDraftNames=new List<string>();
 internal static bool OptionalMentionNamesMatch(IEnumerable<string> actual,IEnumerable<string> planned){var a=actual.ToList();var p=planned.ToList();return a.Distinct().All(n=>a.Count(x=>x==n)<=p.Count(x=>x==n));}
 internal static bool CanKeepLiteralMention(string before,string name,string actual,IEnumerable<string> labels){return QQTextMatches(actual,before+"@"+name)&&labels.OrderBy(n=>n).SequenceEqual(NativeDraftNames.Select(n=>"@"+n).OrderBy(n=>n));}
 internal static List<string> QQMemberNames(ANode root){
  var list=All(root).FirstOrDefault(n=>n.name=="群成员列表");if(list==null)return new List<string>();
  var rows=list.children;
  // QQ wraps all member rows in one or more anonymous containers. Do not take
  // only the first text leaf of that wrapper, or lose duplicate-name evidence.
  while(rows.Count==1&&rows[0].children.Count>0&&!rows[0].children.Any(n=>n.role==41))rows=rows[0].children;
  return rows.Select(n=>All(n).Where(x=>x.role==41&&x.name!="").Select(x=>x.name).FirstOrDefault()).Where(n=>!string.IsNullOrEmpty(n)).ToList();
 }
 static string MemberCachePrefix {get{return "name:"+Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(group))+":";}}
 static List<string> CachedMemberNames(){try{if(!File.Exists(MemberCachePath))return new List<string>();var cache=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(MemberCachePath));return cache.Where(p=>p.Key.StartsWith(MemberCachePrefix,StringComparison.Ordinal)).Select(p=>p.Key.Substring(MemberCachePrefix.Length)).ToList();}catch{return new List<string>();}}
 internal static List<MentionPart> MentionPlan(string text,IEnumerable<string> members){
  var result=new List<MentionPart>();var names=members.Distinct().OrderByDescending(n=>n.Length).ToList();int last=0;
  // Protect code, URLs and mail addresses. A bare @ has no target.
  foreach(Match match in Regex.Matches(text,@"```[\s\S]*?(?:```|$)|`[^`\r\n]*(?:`|$)|https?://[^\s<>]+|[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}|(?<![A-Za-z0-9_.%+\-/])@")){
   if(match.Value!="@")continue;int at=match.Index;if(at<last)continue;string rest=text.Substring(at+1);
   string name=names.FirstOrDefault(n=>rest.StartsWith(n,StringComparison.Ordinal)&&(rest.Length==n.Length||Regex.IsMatch(rest.Substring(n.Length,1),@"[\s，。！？!?,:：;；、@/）)\]】]")));
   if(name==null){var found=Regex.Match(rest,@"^[^\s@，。！？!?,:：;；、<>/（）()\[\]【】`\""']{1,64}");if(!found.Success)continue;name=found.Value;}
   if(name=="全体成员"||name=="全体"||name=="all")throw new Exception("MENTION_ALL_BLOCKED: 不自动创建 @全体成员");
   if(at>last)result.Add(new MentionPart(text.Substring(last,at-last)));result.Add(new MentionPart("@"+name,name));last=at+1+name.Length;
   // A bot command is opaque clipboard text. Its parameters may contain literal
   // @, slashes, quotes or code; never reinterpret them as more member selections.
   string tail=text.Substring(last);
   if(Regex.IsMatch(tail,@"^\s*/")){result.Add(new MentionPart(tail,null,true));last=text.Length;break;}
  }
  if(last<text.Length)result.Add(new MentionPart(text.Substring(last)));if(result.Count(p=>p.name!=null&&names.Contains(p.name))>4)throw new Exception("MENTION_LIMIT: 单条最多原生提及4次");return result;
 }
 internal static List<string> DraftMentionLabels(ANode input){return All(input).Where(n=>n.role==20&&n.parent!=input&&n.children.Count==1&&n.children[0].role==41&&n.children[0].name.StartsWith("@")).Select(n=>n.children[0].name).ToList();}
 static string ComparableQQDraft(string text){
  string value=QQDraftText(text);if(!NativeDraftNames.Any())return value;
  string comparable="";bool afterMention=false;
  foreach(var part in MentionPlan(value,NativeDraftNames)){
   if(part.name!=null&&NativeDraftNames.Contains(part.name)){comparable+=part.text;afterMention=true;}
   else{comparable+=afterMention?part.text.TrimStart(' ','\u00a0'):part.text;afterMention=false;}
  }
  return comparable;
 }
 internal static bool QQTextMatches(string actual,string expected){return ComparableQQDraft(actual)==ComparableQQDraft(expected);}
 static void VerifyNativeDraft(ANode input){if(!NativeDraftNames.Any())return;var labels=DraftMentionLabels(input);if(labels.Count!=NativeDraftNames.Count)throw new Exception("MENTION_PROOF_FAILED: 出现计划外的原生提及，未执行发送");foreach(var name in NativeDraftNames.Distinct())if(labels.Count(n=>n=="@"+name)!=NativeDraftNames.Count(n=>n==name))throw new Exception("MENTION_PROOF_FAILED: 原生提及结构已变化，未执行发送");}
 static void TypeCharacters(string text){foreach(char c in text){if(GetForegroundWindow()!=qq){try{RememberOwnedQQDraft();}catch{}throw new Exception("QQ 焦点已变化，未继续输入");}var a=new[]{new INPUT{type=1,u=new UNION{ki=new KEY{scan=c,flags=4}}},new INPUT{type=1,u=new UNION{ki=new KEY{scan=c,flags=6}}}};if(SendInput(2,a,Marshal.SizeOf(typeof(INPUT)))!=2)throw new Exception("文字输入未完成");}}
 static void AppendQQText(string text,bool commandTail=false){
  if(text.Length==0)return;FocusQQInput(cachedQQInput);Key(0x11,true);try{Press(0x23);}finally{Key(0x11,false);}
  string normalized=text.Replace("\r\n","\n"),paste=commandTail?normalized:normalized.TrimEnd('\n');int breaks=commandTail?0:normalized.Length-paste.Length;
  string before=Value(cachedQQInput);var previous=Clipboard.GetDataObject();
  try{
   if(paste.Length>0){Clipboard.SetText(paste,TextDataFormat.UnicodeText);Key(0x11,true);try{Thread.Sleep(25);Press(0x56);Thread.Sleep(30);}finally{Key(0x11,false);}}
   var watch=Stopwatch.StartNew();bool ready=paste.Length==0;while(!ready&&watch.ElapsedMilliseconds<1800){Thread.Sleep(30);Pump();string actual=QQReadStable(()=>Value(cachedQQInput));ready=watch.ElapsedMilliseconds>160&&(commandTail?QQTextMatches(actual,before+paste):CanonicalText(actual)==CanonicalText(before+paste));}
   if(!ready)throw new Exception("MENTION_APPEND_FAILED: 提及后的正文粘贴校验失败，未发送");
   // QQ can discard terminal paragraph breaks on paste. Insert real editor line
   // breaks before the next mention so it cannot attach to the preceding paragraph.
   for(int i=0;i<breaks;i++){Key(0x10,true);try{Press(0x0d);}finally{Key(0x10,false);}Thread.Sleep(35);Pump();}
  }finally{try{if(Clipboard.ContainsText()&&Clipboard.GetText()==paste){if(previous!=null)Clipboard.SetDataObject(previous,true);else Clipboard.Clear();}}catch{}}
 }
 static void CacheSelectedMember(string name){
  try{Dictionary<string,object> cache=File.Exists(MemberCachePath)?Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(MemberCachePath)):new Dictionary<string,object>();
   cache[MemberCachePrefix+name]=new{name=name,groupName=group,groupId=groupId,verifiedAt=DateTime.UtcNow.ToString("o"),method="qq-native-picker",account=(string)null};
   File.WriteAllText(MemberCachePath,Json.Serialize(cache));
  }catch{} // The cache is diagnostic only; it never authorizes a candidate.
 }
 static void SelectQQMention(string name){
  var before=Value(cachedQQInput);FocusQQInput(cachedQQInput);Key(0x11,true);try{Press(0x23);}finally{Key(0x11,false);}
  Key(0x10,true);try{Press(0x32);Thread.Sleep(25);}finally{Key(0x10,false);}Thread.Sleep(80);Pump();TypeCharacters(name);RememberOwnedQQDraft();
  ANode candidate=null;var watch=Stopwatch.StartNew();
  while(watch.ElapsedMilliseconds<2200){Thread.Sleep(55);Pump();var root=QQTree();var list=All(root).FirstOrDefault(n=>n.name=="成员列表");if(list==null)continue;
   var matches=All(list).Where(n=>n.role==41&&n.name==name&&(n.state&0x18000)==0).ToList();
   if(matches.Count>1){KeepLiteralQQMention(before,name);return;}
   if(watch.ElapsedMilliseconds>=300&&matches.Count==1){candidate=matches[0];break;}
  }
  if(candidate==null){KeepLiteralQQMention(before,name);return;}
  Click(candidate,qq);watch.Restart();while(watch.ElapsedMilliseconds<1800){Thread.Sleep(40);Pump();var root=QQTree();if(!All(root).Any(n=>n.name=="成员列表")&&DraftMentionLabels(cachedQQInput).Count(n=>n=="@"+name)>NativeDraftNames.Count(n=>n==name)){NativeDraftNames.Add(name);if(CanonicalText(Value(cachedQQInput))!=CanonicalText(before+"@"+name))throw new Exception("MENTION_PROOF_FAILED: 成员选择后草稿不一致");CacheSelectedMember(name);return;}}
  throw new Exception("MENTION_PROOF_FAILED: 未确认客户端创建原生提及，未发送");
 }
 static void KeepLiteralQQMention(string before,string name){
  // No candidate has been clicked. Escape only dismisses the picker; retain the
  // exact typed @name and all prior native mentions, without rebuilding the draft.
  if(GetForegroundWindow()!=qq)throw new Exception("QQ 焦点已变化，未继续输入");
  var root=QQTree();if(!CanKeepLiteralMention(before,name,Value(cachedQQInput),DraftMentionLabels(cachedQQInput)))throw new Exception("MENTION_PROOF_FAILED: 未匹配名字的草稿已变化，未发送");
  Press(0x1b);var watch=Stopwatch.StartNew();
  while(watch.ElapsedMilliseconds<800){Thread.Sleep(40);Pump();root=QQTree();if(GetForegroundWindow()!=qq)throw new Exception("QQ 焦点已变化，未继续输入");if(!All(root).Any(n=>n.name=="成员列表")){
   if(!CanKeepLiteralMention(before,name,Value(cachedQQInput),DraftMentionLabels(cachedQQInput)))throw new Exception("MENTION_PROOF_FAILED: 普通名字回退校验失败，未发送");RememberOwnedQQDraft();return;
  }}throw new Exception("MENTION_PROOF_FAILED: 无法关闭成员候选，未发送");
 }
 static void ComposeQQText(ANode input,string text){
  NativeDraftNames.Clear();if(!nativeMentions||!text.Contains("@")){PutQQ(input,text);return;}
  var members=QQMemberNames(QQTree());var plan=MentionPlan(text,members.Concat(CachedMemberNames()));if(!plan.Any(p=>p.name!=null)){PutQQ(input,text);return;}
  foreach(var target in plan.Where(p=>p.name!=null))if(members.Count(n=>n==target.name)>1)target.name=null;
  // Build through actual editor operations; never paste a forged mention payload.
  foreach(var part in plan){if(part.name!=null&&NativeDraftNames.Count<4)SelectQQMention(part.name);else AppendQQText(part.text,part.commandTail);RememberOwnedQQDraft();}
  if(!QQTextMatches(Value(cachedQQInput),text))throw new Exception("MENTION_PROOF_FAILED: 提及草稿与回复不一致，未发送");VerifyNativeDraft(cachedQQInput);
 }
}
