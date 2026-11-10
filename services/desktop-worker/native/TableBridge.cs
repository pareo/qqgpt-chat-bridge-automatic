// Deterministic local table layout. No UI, clipboard, network or AI calls.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

partial class Bridge {
 internal class TableRowImage {public int index;public List<string>[] lines;public bool continued;}
 internal class TablePageImage {public int[] columns;public List<string>[] header;public List<TableRowImage> rows=new List<TableRowImage>();public int headerHeight,height;}
 const int TableWidth=1080,TableMargin=28,TablePad=18,TableLine=40,TableTop=76,TableBottom=54,TableMaxHeight=1500;
 static int[] TableColumnWidths(int count){if(count==1)return new[]{TableWidth};int first=count==2?300:220;return Enumerable.Range(0,count).Select(i=>i==0?first:(TableWidth-first)/(count-1)).ToArray();}
 static List<string> TableWrap(Graphics g,Font font,string value,int width){
  var lines=new List<string>();var text=(value??"").Replace("\r\n","\n").Replace('\r','\n').Replace("\t","    ");
  using(var format=(StringFormat)StringFormat.GenericTypographic.Clone()){
   format.FormatFlags|=StringFormatFlags.MeasureTrailingSpaces;
   foreach(var paragraph in text.Split('\n')){
    var buffer=new StringBuilder();float used=0;var elements=StringInfo.GetTextElementEnumerator(paragraph);
    while(elements.MoveNext()){string element=elements.GetTextElement();float size=g.MeasureString(element,font,PointF.Empty,format).Width;
     if(buffer.Length>0&&used+size>width){lines.Add(buffer.ToString());buffer.Length=0;used=0;}
     buffer.Append(element);used+=size;
    }
    lines.Add(buffer.ToString());
   }
  }
  return lines.Count>0?lines:new List<string>{""};
 }
 internal static List<string> RenderTablePng(string[][] input,bool hasHeader,int maxPages){
  if(input==null||input.Length==0||input.Length>500||maxPages<1||maxPages>16)throw new Exception("表格行数或分页上限不合法");
  int columns=input.Max(row=>row==null?0:row.Length);if(columns<1||columns>16)throw new Exception("表格列数超过16列，未截断内容");
  if(input.Any(row=>row==null||row.Any(cell=>cell!=null&&cell.Length>12000))||input.Sum(row=>row.Sum(cell=>(cell??"").Length))>150000)throw new Exception("表格内容过大，未截断内容");
  var grid=input.Select(row=>Enumerable.Range(0,columns).Select(i=>i<row.Length?row[i]??"":"").ToArray()).ToArray();
  string[] headers=hasHeader?grid[0]:Enumerable.Range(1,columns).Select(i=>"第"+i+"列").ToArray();
  var data=hasHeader?grid.Skip(1).ToArray():grid;
  var panels=new List<int[]>();if(columns<=4)panels.Add(Enumerable.Range(0,columns).ToArray());
  else for(int at=1;at<columns;at+=3)panels.Add(new[]{0}.Concat(Enumerable.Range(at,Math.Min(3,columns-at))).ToArray());
  var pages=new List<TablePageImage>();
  using(var sample=new Bitmap(1,1))using(var graphics=Graphics.FromImage(sample))using(var font=new Font("Microsoft YaHei UI",26,FontStyle.Regular,GraphicsUnit.Pixel))using(var bold=new Font("Microsoft YaHei UI",27,FontStyle.Bold,GraphicsUnit.Pixel)){
   foreach(var panel in panels){
    var widths=TableColumnWidths(panel.Length);var header=panel.Select((c,i)=>TableWrap(graphics,bold,headers[c],widths[i]-TablePad*2)).ToArray();
    int headerHeight=header.Max(lines=>lines.Count)*TableLine+2*TablePad;
    if(headerHeight>500)throw new Exception("表头过长，无法生成可读图片；请缩短表头");
    var page=new TablePageImage{columns=panel,header=header,headerHeight=headerHeight};pages.Add(page);
    int used=TableTop+headerHeight;
    for(int row=0;row<data.Length;row++){
     var lines=panel.Select((c,i)=>TableWrap(graphics,font,data[row][c],widths[i]-TablePad*2)).ToArray();int total=lines.Max(l=>l.Count),offset=0;
     while(offset<total){
      int available=(TableMaxHeight-used-TableBottom-TablePad*2)/TableLine;
      if(available<1){page.height=used+TableBottom;page=new TablePageImage{columns=panel,header=header,headerHeight=headerHeight};pages.Add(page);used=TableTop+headerHeight;continue;}
      int count=Math.Min(total-offset,available);var section=lines.Select(l=>l.Skip(offset).Take(count).ToList()).ToArray();
      if(offset>0&&section[0].Count==0)section[0]=new List<string>{(lines[0].FirstOrDefault()??"")+"（续）"};
      page.rows.Add(new TableRowImage{index=row,lines=section,continued=offset>0});used+=count*TableLine+TablePad*2;offset+=count;
     }
    }
    page.height=used+TableBottom;
   }
   if(pages.Count>maxPages)throw new Exception("表格需要"+pages.Count+"张图片，超过media.maxImages上限；未缩小字体或丢弃内容");
   Directory.CreateDirectory(MediaRoot);string hash;
   using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes("table-v1|"+hasHeader+"|"+Json.Serialize(grid)))).Replace("-","").ToLowerInvariant();
   var paths=new List<string>();
   for(int i=0;i<pages.Count;i++){
    string target=Path.Combine(MediaRoot,"table-"+hash+"-"+(i+1)+".png");paths.Add(target);if(File.Exists(target))continue;
    var p=pages[i];var widths=TableColumnWidths(p.columns.Length);
    using(var image=new Bitmap(TableWidth+TableMargin*2,p.height,PixelFormat.Format24bppRgb))using(var g=Graphics.FromImage(image))
    using(var ink=new SolidBrush(Color.FromArgb(28,41,61)))using(var muted=new SolidBrush(Color.FromArgb(104,119,139)))using(var white=new SolidBrush(Color.White))
    using(var blue=new SolidBrush(Color.FromArgb(44,85,151)))using(var alternate=new SolidBrush(Color.FromArgb(241,245,250)))using(var rule=new Pen(Color.FromArgb(214,223,235)))
    using(var title=new Font("Microsoft YaHei UI",30,FontStyle.Bold,GraphicsUnit.Pixel))using(var footer=new Font("Microsoft YaHei UI",19,FontStyle.Regular,GraphicsUnit.Pixel)){
     g.Clear(Color.FromArgb(248,250,253));g.TextRenderingHint=TextRenderingHint.AntiAliasGridFit;
     g.DrawString("表格",title,ink,TableMargin,22);int y=TableTop,x=TableMargin;
     for(int c=0;c<widths.Length;c++){g.FillRectangle(blue,x,y,widths[c],p.headerHeight);for(int line=0;line<p.header[c].Count;line++)g.DrawString(p.header[c][line],bold,white,x+TablePad,y+TablePad+line*TableLine);x+=widths[c];}
     y+=p.headerHeight;
     foreach(var row in p.rows){int height=row.lines.Max(l=>l.Count)*TableLine+TablePad*2;x=TableMargin;
      for(int c=0;c<widths.Length;c++){g.FillRectangle(row.index%2==0?white:alternate,x,y,widths[c],height);for(int line=0;line<row.lines[c].Count;line++)g.DrawString(row.lines[c][line],font,ink,x+TablePad,y+TablePad+line*TableLine);g.DrawRectangle(rule,x,y,widths[c],height);x+=widths[c];}y+=height;
     }
     g.DrawString("第 "+(i+1)+" / "+pages.Count+" 页",footer,muted,TableMargin,y+14);
     string temporary=target+"."+Guid.NewGuid().ToString("N")+".tmp";
     try{image.Save(temporary,ImageFormat.Png);File.Move(temporary,target);}finally{if(File.Exists(temporary))File.Delete(temporary);}
    }
   }
   return paths;
  }
 }
 static object RenderTableImages(Dictionary<string,object> d){
  if(!d.ContainsKey("rows")||!(d["rows"] is IEnumerable)||d["rows"] is string)throw new Exception("缺少表格数据");
  var rows=new List<string[]>();foreach(var row in (IEnumerable)d["rows"]){if(!(row is IEnumerable)||row is string)throw new Exception("表格行数据无效");rows.Add(((IEnumerable)row).Cast<object>().Select(value=>Convert.ToString(value)).ToArray());}
  int maxPages=d.ContainsKey("maxPages")?Convert.ToInt32(d["maxPages"]):4;bool hasHeader=!d.ContainsKey("hasHeader")||B(d,"hasHeader");
  return new{images=RenderTablePng(rows.ToArray(),hasHeader,maxPages).Select(file=>new{path=file}).ToArray()};
 }
}
