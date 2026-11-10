using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Threading;

partial class Bridge {
 static string ownedAppExpected=null,ownedAppCheckpoint=null;
 static List<string> ownedAppAttachments=new List<string>();
 static string ownedBrowserExpected=null,ownedBrowserCheckpoint=null,ownedBrowserUrl=null;
 static string recoveryQQImagePath=null,recoveryQQImageDraft=null;
 internal static bool CanClearOwnedQQImage(string draft,string checkpoint,int count,bool committed,bool owned){return owned&&!committed&&count==1&&checkpoint!=null&&draft==checkpoint;}
 static void RememberQQRecoveryImage(){try{var input=QQInput(QQTree());string draft=Value(input);if(All(input).Count(IsQQImage)==1&&string.IsNullOrWhiteSpace(draft.Replace("\u200b","")))recoveryQQImageDraft=draft;}catch{}}
 internal static bool RecoverableTextDraft(string draft,string expected,string checkpoint,bool allowUnknown){return draft==""||allowUnknown||expected!=null&&(draft==expected.Trim()||checkpoint!=null&&draft==checkpoint);}
 internal static bool RecoveryAttachmentNamesMatch(IEnumerable<string> actual,IEnumerable<string> owned){return actual.OrderBy(n=>n).SequenceEqual(owned.OrderBy(n=>n));}
 internal static bool CanDiscardAppDraft(bool confirmed,string draft,string expected,IEnumerable<string> actual,IEnumerable<string> observed,bool generating){return confirmed&&!generating&&!string.IsNullOrEmpty(expected)&&draft==expected.Trim()&&RecoveryAttachmentNamesMatch(actual,observed);}
 static object DiscardAppDraft(string expected,string title,string[] observed,bool confirmed){
  if(string.IsNullOrEmpty(title))throw new Exception("清空草稿缺少目标会话");appTitle=title;var root=AppRoot();AppGuard(root);
  var draft=AppDraft(AppInput(root));var attachments=RecoveryAttachmentButtons(root);
  if(!CanDiscardAppDraft(confirmed,draft,expected,attachments.Select(n=>n.name),observed,AppGenerating(root)))throw new Exception("草稿或附件与人工确认的内容不符，未清空");
  BackupRecoveryDraft("chatgpt-operator",draft,attachments.Select(n=>n.name).ToArray());commandDraftTouched=true;
  // Explicit operator cleanup may remove the observed draft even when upload
  // completion renamed its chips. Automatic recovery retains its stricter rules.
  for(int remaining=attachments.Count;remaining>0;remaining--){
   root=AppRoot();AppGuard(root);if(AppDraft(AppInput(root))!=draft||AppAttachmentCount(root)!=remaining||AppGenerating(root))throw new Exception("清空过程中草稿或附件数量发生变化");
   Click(RecoveryAttachmentButtons(root)[0],chatApp);int next=remaining-1;root=AppWait(t=>AppAttachmentCount(t)==next&&AppDraft(AppInput(t))==draft);
  }
  root=AppRoot();AppGuard(root);var input=AppInput(root);if(AppDraft(input)!=draft)throw new Exception("草稿已变化，未清空文字");
  try{Put(input,"",chatApp);}catch{root=AppRoot();AppGuard(root);if(AppDraft(AppInput(root))!="")throw;}
  root=AppWait(t=>AppDraft(AppInput(t))==""&&AppAttachmentCount(t)==0);
  expectedAppAttachments=0;pendingAppImage=null;ownedAppExpected=ownedAppCheckpoint=null;ownedAppAttachments.Clear();return new{cleared=true};
 }
 static void BackupRecoveryDraft(string channel,string draft,object attachments){
  if(draft==""&&attachments==null)return;
  string directory=Path.Combine(WorkerStateRoot,"draft-backups");Directory.CreateDirectory(directory);
  File.WriteAllText(Path.Combine(directory,channel+"-"+Guid.NewGuid().ToString("N")+".private.json"),Json.Serialize(new{channel=channel,text=draft,attachments=attachments,time=DateTime.UtcNow.ToString("o")}));
 }
 static List<ANode> RecoveryAttachmentButtons(ANode root){return All(AppComposer(root)).Where(AppRemoveAttachmentControl).ToList();}
 static void RememberAppComposer(bool afterUpload=false){try{var root=AppRoot();AppGuard(root);string draft=AppDraft(AppInput(root));if(ownedAppExpected!=null&&(draft==""||ownedAppExpected.Trim().StartsWith(draft,StringComparison.Ordinal)))ownedAppCheckpoint=draft;var names=RecoveryAttachmentButtons(root).Select(n=>n.name).ToList();if(afterUpload&&pendingAppImage!=null&&names.Count==pendingAppImageBefore+1&&ownedAppAttachments.All(n=>names.Contains(n)))ownedAppAttachments=names;}catch{}}
 internal static bool LatestAppPromptMatches(ANode root,string expected){
  if(string.IsNullOrEmpty(expected))return false;var region=AppConversation(root);if(region==null)return false;
  var nodes=All(region).ToList();int at=nodes.FindLastIndex(n=>n.role==20&&(n.name=="你说："||n.name=="You said:"));if(at<0)return false;
  int end=nodes.FindIndex(at+1,n=>n.role==20&&(n.name=="ChatGPT 说："||n.name=="ChatGPT said:"));
  int userEnd=nodes.FindIndex(at+1,n=>n.role==43&&(n.name=="复制消息"||n.name=="Copy message"));
  if(userEnd>=0&&(end<0||userEnd<end))end=userEnd;
  var segment=nodes.Skip(at+1).Take((end<0?nodes.Count:end)-at-1).ToList();
  var fileNames=new HashSet<string>(segment.Where(n=>n.role==43&&System.Text.RegularExpressions.Regex.IsMatch(n.name,@"\.[A-Za-z0-9]{1,12}$")).Select(n=>n.name));
  var texts=segment.Where(n=>n.role==41&&n.name!="你说："&&n.name!="You said:"&&!ControlAncestor(n)).Select(n=>n.name);
  // File captions precede the actual prompt. Strip only this verified leading
  // metadata; matching labels inside the question remain part of its text.
  if(fileNames.Count>0)texts=texts.SkipWhile(s=>fileNames.Contains(s)||s=="文档"||s=="Document");
  string actual=string.Join("",texts);
  return CanonicalText(actual)==CanonicalText(expected)||CanonicalText(actual)==CanonicalText(RenderedPromptText(expected));
 }
 static bool ControlAncestor(ANode node){for(var p=node.parent;p!=null;p=p.parent)if(p.role==43||p.role==57)return true;return false;}
 internal static string RenderedPromptText(string expected){
  string fence=null;var lines=new List<string>();var plain=new List<string>();
  foreach(string line in expected.Replace("\r\n","\n").Replace('\r','\n').Split('\n')){
   var mark=System.Text.RegularExpressions.Regex.Match(line,@"^\s*(`{3,}|~{3,})([^\r\n]*)$");
   if(fence==null&&mark.Success&&!(mark.Groups[1].Value[0]=='`'&&mark.Groups[2].Value.Contains("`"))){lines.Add(PromptInlineText(string.Join("\n",plain)));plain.Clear();fence=mark.Groups[1].Value;continue;}
   if(fence!=null&&mark.Success&&mark.Groups[1].Value[0]==fence[0]&&mark.Groups[1].Value.Length>=fence.Length&&mark.Groups[2].Value.Trim()==""){fence=null;continue;}
   if(fence!=null)lines.Add(line);else plain.Add(line);
  }
  lines.Add(PromptInlineText(string.Join("\n",plain)));
  return string.Join("\n",lines);
 }
 static string PromptInlineText(string text){
  var runs=System.Text.RegularExpressions.Regex.Matches(text,"`+");var result=new System.Text.StringBuilder();int at=0;
  for(int i=0;i<runs.Count;i++){
   var open=runs[i];int slash=0;for(int p=open.Index-1;p>=0&&text[p]=='\\';p--)slash++;if(slash%2!=0)continue;
   int end=i+1;while(end<runs.Count&&runs[end].Length!=open.Length)end++;if(end==runs.Count)continue;
   result.Append(text.Substring(at,open.Index-at));result.Append(text.Substring(open.Index+open.Length,runs[end].Index-open.Index-open.Length));at=runs[end].Index+runs[end].Length;i=end;
  }
  result.Append(text.Substring(at));return result.ToString();
 }
 static object RecoverApp(string expected,string title,bool allowUnknown,bool clear,bool stopOwned){
  if(string.IsNullOrEmpty(title))throw new Exception("恢复AI会话缺少目标标题");appTitle=title;
  var root=AppRoot();AppGuard(root);var expand=AppPromptExpandButton(root);if(expand!=null){Click(expand,chatApp);Thread.Sleep(100);root=AppRoot();AppGuard(root);}
  bool latest=LatestAppPromptMatches(root,expected),generating=AppGenerating(root),stoppedReply=false;
  if(generating){
   if(!stopOwned||!latest)return new{ready=false,latestMatches=latest,wasGenerating=true,reason="当前生成无法归属本任务"};
   var stop=Unique(All(root).Where(n=>n.role==43&&(n.name=="停止"||n.name=="Stop"||n.name=="停止生成")),"本任务停止生成按钮");Click(stop,chatApp);root=AppWait(t=>!AppGenerating(t),5000);AppGuard(root);stoppedReply=true;
  }
  string draft=AppDraft(AppInput(root));var attachments=RecoveryAttachmentButtons(root);
  if(draft==""&&attachments.Count==0){expectedAppAttachments=0;pendingAppImage=null;ownedAppExpected=ownedAppCheckpoint=null;ownedAppAttachments.Clear();return new{ready=true,latestMatches=latest,wasGenerating=stoppedReply};}
  if(!clear||!RecoverableTextDraft(draft,expected==""?ownedAppExpected:expected,ownedAppCheckpoint,allowUnknown))return new{ready=false,latestMatches=latest,wasGenerating=stoppedReply,reason="草稿未获准清理"};
  // Unknown image attachments cannot be backed up as text. Only remove the exact
  // attachment buttons recorded after this process's own upload operations.
  if(!RecoveryAttachmentNamesMatch(attachments.Select(n=>n.name),ownedAppAttachments))return new{ready=false,latestMatches=latest,wasGenerating=stoppedReply,reason="存在未归属的人工附件"};
  BackupRecoveryDraft("chatgpt",draft,attachments.Select(n=>n.name).ToArray());
  for(int i=attachments.Count;i>0;i--){root=AppRoot();AppGuard(root);if(AppDraft(AppInput(root))!=draft)throw new Exception("恢复时AI草稿已变化，未继续清理");var current=RecoveryAttachmentButtons(root);if(!RecoveryAttachmentNamesMatch(current.Select(n=>n.name),ownedAppAttachments))throw new Exception("恢复时AI附件已变化");string removed=current[0].name;Invoke(current[0],chatApp);ownedAppAttachments.Remove(removed);root=AppWait(t=>RecoveryAttachmentButtons(t).Count==i-1);}
  root=AppRoot();AppGuard(root);var input=AppInput(root);Front(chatApp);if(AppDraft(input)!=draft)throw new Exception("恢复时AI草稿已变化，未继续清理");commandDraftTouched=true;Put(input,"",chatApp);root=AppWait(t=>AppDraft(AppInput(t))==""&&AppAttachmentCount(t)==0);
  expectedAppAttachments=0;pendingAppImage=null;ownedAppExpected=ownedAppCheckpoint=null;ownedAppAttachments.Clear();return new{ready=true,latestMatches=latest,wasGenerating=stoppedReply,cleared=true};
 }
 static object RecoverBrowser(string expected,string url,bool allowUnknown,bool clear){
  var doc=ChromeTree();CheckModel(doc);if(!Allowed(url)||new Uri(doc.value).AbsolutePath!=new Uri(url).AbsolutePath)throw new Exception("恢复网页会话不匹配，未清理");
  if(All(doc).Any(n=>n.role==43&&(n.name=="stop-response-button"||n.name=="stop-message-button"||n.name=="停止生成")))return new{ready=false,reason="网页仍在生成，等待后再试"};
  var input=BrowserInput(doc);string draft=Draft(input);if(draft=="")return new{ready=true};
  if(!clear||!RecoverableTextDraft(draft,expected==""?ownedBrowserExpected:expected,ownedBrowserCheckpoint,allowUnknown))return new{ready=false,reason="网页草稿未获准清理"};
  BackupRecoveryDraft("openwebui",draft,null);if(Draft(input)!=draft)throw new Exception("恢复时网页草稿已变化，未清理");commandDraftTouched=true;Put(input,"",chrome);if(Draft(input)!="")throw new Exception("网页草稿清理未确认");ownedBrowserExpected=ownedBrowserCheckpoint=null;return new{ready=true,cleared=true};
 }
 static object RecoverQQ(bool allowUnknown,bool clear){
  var input=QQInput(VerifyGroup());string draft=Value(input);
  if(draft==""&&!All(input).Any(IsQQImage))return new{ready=true};
  bool ownedImage=CanClearOwnedQQImage(draft,recoveryQQImageDraft,All(input).Count(IsQQImage),qqCommitPending,recoveryQQImagePath!=null);
  if(!clear||qqCommitPending||All(input).Any(IsQQImage)&&!ownedImage)return new{ready=false,reason="QQ存在未归属图片或可能已提交的草稿"};
  if(!allowUnknown&&!ownedImage&&!QQOwnedDraftMatches(draft,ownedQQExpected,ownedQQCheckpoint,false,false))return new{ready=false,reason="QQ草稿未获准清理"};
  BackupRecoveryDraft("qq",draft,new{mentions=DraftMentionLabels(input).ToArray(),image=ownedImage?recoveryQQImagePath:null});if(Value(input)!=draft)throw new Exception("恢复时QQ草稿已变化，未清理");commandDraftTouched=true;PutQQ(input,"",draft);input=QQInput(QQTree());if(Value(input)!=""||All(input).Any(IsQQImage))throw new Exception("QQ草稿清理未确认");ownedQQExpected=ownedQQCheckpoint=null;recoveryQQImagePath=recoveryQQImageDraft=null;NativeDraftNames.Clear();return new{ready=true,cleared=true};
 }
}
