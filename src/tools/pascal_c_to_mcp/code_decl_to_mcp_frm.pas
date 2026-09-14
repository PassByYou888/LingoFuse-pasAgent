unit code_decl_to_mcp_frm;

{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\..\Z.Define.inc}

interface

uses
  Classes, SysUtils, Forms, Controls, Graphics, Dialogs, StdCtrls, ExtCtrls,
  LazHelpHTML, ComCtrls, Menus, AsyncProcess, ActnList,
  LCLIntf,
  SynHighlighterCpp, SynHighlighterAny, lingofuse_helper,
  Z.Core, Z.PascalStrings, Z.UPascalStrings,
  Z.Parsing, Z.Expression, Z.ListEngine, Z.Notify, Z.UnicodeMixedLib, Z.Status,
  Z.MemoryStream, Z.Json, Z.HashList.Templet, SynEdit, SynHighlighterPas, SynEditMiscClasses,
  lingofuse_import, pas_mcp_generator_tool, py_mcp_generator_tool, Z.Pascal_Func_Model, Z.Pascal_Func_Tool;

type

  { Tcode_decl_to_mcp_form }

  Tcode_decl_to_mcp_form = class(TForm)
    Bevel1: TBevel;
    Bevel10: TBevel;
    Bevel2: TBevel;
    Bevel8: TBevel;
    Bevel9: TBevel;
    empty_unit_Button: TButton;
    empty_unit_Button1: TButton;
    final_pascal_source_Edit: TSynEdit;
    final_py_source_Edit: TSynEdit;
    Formater_source_Button: TButton;
    Label11: TLabel;
    Open_unit_readme_Button6: TButton;
    PageControl1: TPageControl;
    Sel_Lang_ComboBox: TComboBox;
    sel_lang_Label: TLabel;
    SourceJsonSpacerBevel1: TBevel;
    SourceJsonSpacerBevel2: TBevel;
    ModelJsonSpacerBevel1: TBevel;
    ModelJsonSpacerBevel2: TBevel;
    FinalSourceSpacerBevel: TBevel;
    source_2_json_nex_Button: TButton;
    source_tool_Panel: TPanel;
    SynCppSyn1: TSynCppSyn;
    pas_TabSheet: TTabSheet;
    Py_TabSheet: TTabSheet;
    to_source_Button: TButton;
    welcomeEdit: TSynEdit;
    ModelToJsonButton: TButton;
    GenerateSourceButton: TButton;
    BackToModelJsonButton: TButton;
    FinalSourceToolPanel: TPanel;
    FinalSourceHintLabel: TLabel;
    ModelJsonHintLabel: TLabel;
    model_json_edit: TSynEdit;
    ModelJsonToolPanel: TPanel;
    JsonToPascalButton: TButton;
    JsonToModelButton: TButton;
    SourceJsonHintLabel: TLabel;
    SourceJsonToolPanel: TPanel;
    source2json_edit: TSynEdit;
    AnyHighlighter: TSynAnySyn;
    SourceJsonTab: TTabSheet;
    ModelJsonTab: TTabSheet;
    FinalSourceTab: TTabSheet;
    SourceTab: TTabSheet;
    FreePascalHighlighter: TSynFreePascalSyn;
    LogMemo: TMemo;
    MainPageControl: TPageControl;
    BottomPanel: TPanel;
    BottomSplitter: TSplitter;
    SysTimer: TTimer;
    source_edit: TSynEdit;
    WelcomeTab: TTabSheet;
    welcome_tool_Panel: TPanel;
    procedure Button3Click(Sender: TObject);
    procedure Button4Click(Sender: TObject);
    procedure Button5Click(Sender: TObject);
    procedure Button6Click(Sender: TObject);
    procedure Button7Click(Sender: TObject);
    procedure empty_unit_Button1Click(Sender: TObject);
    procedure empty_unit_ButtonClick(Sender: TObject);
    procedure Open_unit_readme_Button6Click(Sender: TObject);
    procedure Sel_Lang_ComboBoxChange(Sender: TObject);
    procedure sel_lang_LabelClick(Sender: TObject);
    procedure source_2_json_nex_ButtonClick(Sender: TObject);
    procedure Formater_source_ButtonClick(Sender: TObject);
    procedure FormClose(Sender: TObject; var CloseAction: TCloseAction);
    procedure sysTimerTimer(Sender: TObject);
    procedure to_source_ButtonClick(Sender: TObject);
  private
    bak_welcome: TP_String;
    current_language: TSourceLanguage;
    procedure Backcall_DoStatus(Text_: SystemString; const ID: integer);
  public
    constructor Create(AOwner: TComponent); override;
    destructor Destroy; override;
    procedure Auto_Select_Language;
  end;

var
  code_decl_to_mcp_form: Tcode_decl_to_mcp_form;

implementation

{$R *.lfm}


procedure Tcode_decl_to_mcp_form.Button3Click(Sender: TObject);
var
  report: TPascalStringList;
begin
  case current_language of
    TSourceLanguage.slPascal:
    begin
      report := TPascalStringList.Create;
      with tpascal_func_decl_tool.Create do
      begin
        LoadFromJson(source2json_edit.Text);
        source_edit.Text := decl_to_pascal(report);
        Free;
      end;
    end;
    TSourceLanguage.slC:
    begin
      report := TPascalStringList.Create;
      with tpascal_func_decl_tool.Create do
      begin
        LoadFromJson(source2json_edit.Text);
        source_edit.Text := decl_to_c(report);
        Free;
      end;
    end;
    else
    begin
      DoStatus('不支持语言.');
      exit;
    end;
  end;

  DoStatus('json->源码构建.');
  DoStatus(report.AsText);
  MainPageControl.ActivePage := SourceTab;
  DisposeObject(report);
end;

procedure Tcode_decl_to_mcp_form.Button4Click(Sender: TObject);
var
  func_tool: tpascal_func_decl_tool;
  func_model: TPascal_Func_Model;
  report: TPascalStringList;
begin
  func_tool := tpascal_func_decl_tool.Create;
  func_tool.LoadFromJson(source2json_edit.Text);

  report := TPascalStringList.Create;

  func_model := TPascal_Func_Model.Create;
  func_model.LoadFromParser(func_tool, report);
  model_json_edit.Text := func_model.SaveToJson;

  DisposeObject(func_tool);

  DoStatus('json -> Model Json构建.');
  DoStatus(report.AsText);
  MainPageControl.ActivePage := ModelJsonTab;
  DisposeObject(report);
end;

procedure Tcode_decl_to_mcp_form.Button5Click(Sender: TObject);
var
  func_tool: tpascal_func_decl_tool;
  func_model: TPascal_Func_Model;
begin
  func_model := TPascal_Func_Model.Create;
  func_model.LoadFromJson(model_json_edit.Text);

  func_tool := tpascal_func_decl_tool.Create;
  func_model.SaveToParser(func_tool);

  source2json_edit.Text := func_tool.SaveToJson;

  DisposeObject(func_tool);
  DisposeObject(func_model);

  MainPageControl.ActivePage := SourceJsonTab;
end;

procedure Tcode_decl_to_mcp_form.Button6Click(Sender: TObject);
var
  func_model: TPascal_Func_Model;
  l: TPascalStringList;
begin
  func_model := TPascal_Func_Model.Create;
  func_model.LoadFromJson(model_json_edit.Text);

  l := GeneratePascalCode(func_model);
  if l <> nil then
  begin
    l.AssignTo(final_pascal_source_Edit.Lines);
    disposeObjectAndNil(l);
  end;

  l := GeneratePythonCode(func_model);
  if l <> nil then
  begin
    l.AssignTo(final_py_source_Edit.Lines);
    disposeObjectAndNil(l);
  end;

  MainPageControl.ActivePage := FinalSourceTab;
  func_model.Free;
end;

procedure Tcode_decl_to_mcp_form.Button7Click(Sender: TObject);
begin
  MainPageControl.ActivePage := ModelJsonTab;
end;

procedure Tcode_decl_to_mcp_form.empty_unit_Button1Click(Sender: TObject);
begin
  case current_language of
    TSourceLanguage.slPascal: source_edit.Text :=
        'unit ComplexTestUnit;'#13#10 + #13#10 + '{'#13#10 + '  这是一个用于测试解析器（Z.Pascal_Func_Tool）的复杂单元。'#13#10 +
        '  包含了各种高级、边缘的语法结构，用于验证解析器的鲁棒性和完整性。'#13#10 +
        '  所有声明均语法正确，但实现部分被省略（仅作为接口声明测试）。'#13#10 +
        '}'#13#10 + #13#10 + '{$mode objfpc}{$H+}'#13#10 + '{$modeswitch advancedrecords}'#13#10 +
        '{$modeswitch typehelpers}'#13#10 + #13#10 + 'interface'#13#10 + #13#10 + 'uses'#13#10 +
        '  SysUtils, Classes, Generics.Collections, TypInfo,'#13#10 + '  Z.Core, Z.PascalStrings, Math;'#13#10 +
        #13#10 + '{ ==========================================================================='#13#10 +
        '  注释风格测试（多种格式）'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + '(* 这是一个顶层函数，没有参数，返回整数 *)'#13#10 + 'function NoParamFunc: Integer;'#13#10 +
        #13#10 + '// 单行注释，过程无参数'#13#10 + 'procedure NoParamProc;'#13#10 + #13#10 + '{'#13#10 +
        '  多行注释块，'#13#10 + '  测试注释提取。'#13#10 + '}'#13#10 + 'function MultiLineComment(a: Integer): Integer;'#13#10 +
        #13#10 + '(**'#13#10 + ' * Doxygen 风格注释'#13#10 + ' * @param a 第一个参数'#13#10 +
        ' * @param b 第二个参数'#13#10 + ' * @return 两数之和'#13#10 + ' *)'#13#10 +
        'function Add(a, b: Integer): Integer;'#13#10 + #13#10 + '{ 注释紧跟函数名 }'#13#10 +
        'function Sub(a, b: Integer): Integer; // 尾随注释不应被绑定'#13#10 + #13#10 +
        '(* 带有星号前缀的注释 *)'#13#10 + '// 另一条注释，连续两条应合并'#13#10 +
        'function Mul(a, b: Double): Double;'#13#10 + #13#10 + '{ ==========================================================================='#13#10
        + '  基本参数声明'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + '// 单个参数'#13#10 + 'function SingleParam(x: Integer): Boolean;'#13#10 + #13#10 +
        '// 多个参数，不同类型'#13#10 + 'function MultipleParams(a: Integer; b: string; c: Double): string;'#13#10 +
        #13#10 + '// var 参数'#13#10 + 'procedure ModifyVar(var Value: Integer);'#13#10 + #13#10 + '// const 参数'#13#10 +
        'procedure ReadOnlyConst(const Value: string);'#13#10 + #13#10 + '// out 参数'#13#10 +
        'procedure GetValue(out Result: Integer);'#13#10 + #13#10 + '// 混合修饰符'#13#10 +
        'procedure MixedMods(const Input: string; var Output: Integer; out ErrorCode: Integer);'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 + '  默认值'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        '// 整数默认值'#13#10 + 'function WithDefaultInt(a: Integer = 42): Integer;'#13#10 + #13#10 +
        '// 字符串默认值（带引号）'#13#10 + 'function WithDefaultString(s: string = '#39'default'#39'): string;'#13#10 +
        #13#10 + '// 布尔默认值'#13#10 + 'function WithDefaultBool(flag: Boolean = True): Boolean;'#13#10 +
        #13#10 + '// 浮点默认值'#13#10 + 'function WithDefaultFloat(pi: Double = 3.14159): Double;'#13#10 +
        #13#10 + '// 常量表达式默认值'#13#10 + 'function WithDefaultConst(x: Integer = MaxBufferSize + 10): Integer;'#13#10 +
        #13#10 + '// 枚举默认值'#13#10 + 'function WithDefaultEnum(c: TColor = clRed): TColor;'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 +
        '  同组多个参数（共享修饰符和类型）'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        '// const 修饰符，多个参数同类型'#13#10 + 'function GroupConst(const a, b, c: Integer): Integer;'#13#10 +
        #13#10 + '// var 修饰符，同类型'#13#10 + 'procedure GroupVar(var x, y, z: Double);'#13#10 + #13#10 +
        '// 混合修饰符，同组不同类型（实际 Pascal 中不允许，但可以测试解析器如何处理）'#13#10 +
        '// 注意：Pascal 语法要求同一组的参数类型必须一致，但这里为了测试混合，我们分开写'#13#10 +
        #13#10 + '// 同组参数带默认值'#13#10 + 'function GroupDefault(const a, b: Integer = 0; const s: string = '#39#39'): Boolean;'#13#10 +
        #13#10 + '// 更复杂：多个组'#13#10 + 'function ComplexGroups(var a, b: Integer; const c: string; out d: Double): Integer;'#13#10 +
        #13#10 + '{ ==========================================================================='#13#10 +
        '  复杂类型参数'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + '// 动态数组'#13#10 + 'procedure ProcessArray(const Arr: array of Integer);'#13#10 + #13#10 +
        '// 静态数组'#13#10 + 'procedure ProcessStaticArray(const Arr: array[0..9] of Integer);'#13#10 + #13#10 +
        '// 记录类型'#13#10 + 'procedure ProcessRecord(const P: TPoint);'#13#10 + #13#10 + '// 类类型'#13#10 +
        'procedure ProcessClass(const Obj: TObject);'#13#10 + #13#10 + '// 泛型类型'#13#10 +
        'procedure ProcessGenericList(const List: TGenericList<string>);'#13#10 + #13#10 +
        '// 函数指针类型（Pascal 中的 procedural type）'#13#10 + 'type'#13#10 + '  TIntFunc = function(x: Integer): Integer;'#13#10 +
        #13#10 + '// 接受函数指针'#13#10 + 'procedure UseFuncPtr(F: TIntFunc);'#13#10 + #13#10 +
        '// 内联函数类型作为参数（使用 reference to）'#13#10 + 'procedure UseAnonymous(const F: reference to procedure);'#13#10 +
        #13#10 + '// 复杂函数类型：带参数和返回值'#13#10 + 'type'#13#10 + '  TBinaryOp = function(a, b: Double): Double;'#13#10 +
        #13#10 + 'procedure UseBinaryOp(Op: TBinaryOp);'#13#10 + #13#10 +
        '// 嵌套函数类型（作为参数类型，包含自己的参数）'#13#10 +
        'procedure UseNestedFunc(F: function(x: Integer): function(y: Integer): Integer);'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 +
        '  带有外部声明和调用约定'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + '// cdecl 调用约定'#13#10 + 'function CdeclFunc(a: Integer): Integer; cdecl;'#13#10 + #13#10 +
        '// stdcall'#13#10 + 'procedure StdcallProc(a: Integer; var b: Double); stdcall;'#13#10 + #13#10 +
        '// register'#13#10 + 'function RegisterFunc(a, b: Integer): Integer; register;'#13#10 + #13#10 +
        '// external 库名'#13#10 + 'function ExternalLib(const Name: PChar): Boolean; cdecl; external '#39'my.dll'#39';'#13#10 +
        #13#10 + '// external + name 别名'#13#10 + 'procedure ExternalAlias; stdcall; external '#39'kernel32'#39' name '#39'GetCurrentProcess'#39';'#13#10 + #13#10 + '// external + index'#13#10 +
        'procedure ExternalIndex; stdcall; external '#39'user32'#39' index 10;'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 + '  重载和继承修饰'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        '// overload'#13#10 + 'function OverloadTest(a: Integer): Integer; overload;'#13#10 +
        'function OverloadTest(a, b: Integer): Integer; overload;'#13#10 + 'function OverloadTest(a: Double): Double; overload;'#13#10 +
        #13#10 + '// virtual / override / abstract'#13#10 + 'type'#13#10 + '  TBase = class'#13#10 +
        '    procedure VirtualProc; virtual;'#13#10 + '    function AbstractFunc: Integer; virtual; abstract;'#13#10 +
        '  end;'#13#10 + #13#10 + '  TDerived = class(TBase)'#13#10 + '    procedure VirtualProc; override;'#13#10 +
        '    function AbstractFunc: Integer; override;'#13#10 + '  end;'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 +
        '  类方法、静态方法、构造函数等'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        'type'#13#10 + '  TMath = class'#13#10 + '  public'#13#10 + '    class function StaticAdd(a, b: Integer): Integer; static;'#13#10 +
        '    class procedure StaticProc; static;'#13#10 + '    constructor Create(a: Integer);'#13#10 +
        '    destructor Destroy; override;'#13#10 + '  end;'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 +
        '  泛型方法（在泛型类内部）'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + 'type'#13#10 + '  TGenericClass<T> = class'#13#10 + '    function GenericMethod<U>(a: T; b: U): T; // 泛型方法'#13#10 +
        '    procedure ProcWithGenericParam(const List: TList<T>);'#13#10 + '  end;'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 +
        '  运算符重载（隐式、显式）'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + 'type'#13#10 + '  TMyRecord = record'#13#10 + '    Value: Integer;'#13#10 +
        '    class operator Implicit(a: Integer): TMyRecord;'#13#10 + '    class operator Explicit(a: Integer): TMyRecord;'#13#10 +
        '    class operator Add(a, b: TMyRecord): TMyRecord;'#13#10 + '  end;'#13#10 + #13#10 +
        '{ ==========================================================================='#13#10 + '  嵌套类型作为参数'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        'type'#13#10 + '  TOuter = class'#13#10 + '  public type'#13#10 + '    TInner = record'#13#10 +
        '      X: Integer;'#13#10 + '    end;'#13#10 + '  end;'#13#10 + #13#10 + 'procedure UseNestedType(const P: TOuter.TInner);'#13#10 +
        #13#10 + '{ ==========================================================================='#13#10 +
        '  复杂默认值（字符串、数组等）'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        '// 字符串默认值包含引号'#13#10 + 'function StringWithQuotes(s: string = '#39'He said: "Hello"'#39'): string;'#13#10 +
        #13#10 + '// 默认值为数组常量（需要支持）'#13#10 +
        '// 注意：Pascal 不支持数组常量作为默认值，但可以试试'#13#10 +
        '// 实际 Delphi/FPC 不允许，所以不包含'#13#10 + #13#10 + '// 默认值为记录常量？也不支持'#13#10 +
        #13#10 + '// 默认值为枚举常量'#13#10 + 'function EnumDefault(c: TColor = clBlue): TColor;'#13#10 +
        #13#10 + '// 默认值为集合常量'#13#10 + 'function SetDefault(s: TOptions = [optRead, optWrite]): TOptions;'#13#10 +
        #13#10 + '{ ==========================================================================='#13#10 +
        '  函数返回值类型为复杂类型'#13#10 + '  =========================================================================== }'#13#10 +
        #13#10 + '// 返回数组'#13#10 + 'function ReturnArray: TIntArray;'#13#10 + #13#10 + '// 返回记录'#13#10 +
        'function ReturnRecord: TPoint;'#13#10 + #13#10 + '// 返回泛型列表'#13#10 +
        'function ReturnGenericList: TGenericList<string>;'#13#10 + #13#10 + '// 返回函数指针'#13#10 +
        'function ReturnFuncPtr: TIntFunc;'#13#10 + #13#10 + '{ ==========================================================================='#13#10 +
        '  带注释的复杂声明（测试注释绑定）'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        '(*'#13#10 + '  这是一个非常复杂的函数声明，包含多个参数组，'#13#10 +
        '  默认值，var/const/out，以及外部指令。'#13#10 + '  注释应该在函数前被正确提取。'#13#10 +
        '*)'#13#10 + 'function SuperComplex('#13#10 + '  const Name: string = '#39'default'#39';    // 第一个参数组，const 修饰符'#13#10 +
        '  var Value: Integer = 42;           // 第二个参数组，var 修饰符，带默认值'#13#10 +
        '  out Flag: Boolean;                 // 第三个参数组，out 修饰符'#13#10 +
        '  const Data: array of Byte          // 第四个参数组，数组类型'#13#10 +
        '): Integer; cdecl; external '#39'lib'#39' name '#39'SuperComplex'#39';'#13#10 + #13#10 +
        '{ 另一个带有函数类型参数的声明 }'#13#10 + '{'#13#10 + '  这是一个使用函数类型作为参数的函数。'#13#10 +
        '  它接受一个二元运算函数，并返回其应用结果。'#13#10 + '}'#13#10 + 'function ApplyBinaryOp('#13#10 +
        '  const Op: TBinaryOp;        // 函数类型参数'#13#10 + '  const a, b: Double = 0.0    // 默认值参数组'#13#10 +
        '): Double; overload;'#13#10 + #13#10 + '// 另一个重载版本，接受整数运算'#13#10 +
        'function ApplyBinaryOp('#13#10 + '  const Op: function(a, b: Integer): Integer;'#13#10 + '  const a, b: Integer = 0'#13#10 +
        '): Integer; overload;'#13#10 + #13#10 + '{ ==========================================================================='#13#10 +
        '  一些附加的复杂结构（类、接口）'#13#10 +
        '  =========================================================================== }'#13#10 + #13#10 +
        'type'#13#10 + '  IMyInterface = interface'#13#10 + '    procedure DoIt;'#13#10 + '  end;'#13#10 + #13#10 +
        '  TMyClass = class(TInterfacedObject, IMyInterface)'#13#10 + '  private'#13#10 + '    FData: TGenericList<TPoint>;'#13#10 +
        '  public'#13#10 + '    constructor Create;'#13#10 + '    procedure DoIt;'#13#10 +
        '    function GetItem(Index: Integer): TPoint;'#13#10 + '    property Items[Index: Integer]: TPoint read GetItem; default;'#13#10 +
        '  end;'#13#10 + #13#10 + 'implementation'#13#10 + #13#10 + 'end.'#13#10;

    TSourceLanguage.slC: source_edit.Text :=
        '/* ComplexTestUnit.h */'#13#10 + #13#10 + '#ifndef ComplexTestUnit_H'#13#10 + '#define ComplexTestUnit_H'#13#10 +
        '/* Generated from unit ComplexTestUnit.h */'#13#10 + #13#10 + '/* 这是一个顶层函数，没有参数，返回整数 */'#13#10 +
        'int NoParamFunc(void);'#13#10 + #13#10 + '/* 单行注释，过程无参数 */'#13#10 + 'void NoParamProc(void);'#13#10 +
        #13#10 + '/* 多行注释块，'#13#10 + '  测试注释提取。 */'#13#10 + 'int MultiLineComment(int a);'#13#10 +
        #13#10 + '/* *'#13#10 + ' * Doxygen 风格注释'#13#10 + ' * @param a 第一个参数'#13#10 +
        ' * @param b 第二个参数'#13#10 + ' * @return 两数之和 */'#13#10 + 'int Add(int a, int b);'#13#10 +
        #13#10 + '/* 注释紧跟函数名 */'#13#10 + 'int Sub(int a, int b);'#13#10 + #13#10 +
        '/* 另一条注释，连续两条应合并 */'#13#10 + 'double Mul(double a, double b);'#13#10 + #13#10 +
        '/* 多个参数，不同类型 */'#13#10 + 'char * MultipleParams(int a, char * b, double c);'#13#10 +
        #13#10 + '/* const 参数 */'#13#10 + 'void ReadOnlyConst(const char * Value);'#13#10 + #13#10 +
        '/* 整数默认值 */'#13#10 + 'int WithDefaultInt(int a);'#13#10 + #13#10 + '/* 字符串默认值（带引号） */'#13#10 +
        'char * WithDefaultString(char * s);'#13#10 + #13#10 + '/* 浮点默认值 */'#13#10 +
        'double WithDefaultFloat(double pi);'#13#10 + #13#10 + '/* 常量表达式默认值 */'#13#10 +
        'int WithDefaultConst(int x);'#13#10 + #13#10 + '/* const 修饰符，多个参数同类型 */'#13#10 +
        'int GroupConst(const int a, const int b, const int c);'#13#10 + #13#10 + '/* cdecl 调用约定 */'#13#10 +
        'int CdeclFunc(int a);'#13#10 + #13#10 + '/* register */'#13#10 + 'int RegisterFunc(int a, int b);'#13#10 +
        #13#10 + '/* external + name 别名 */'#13#10 + 'void ExternalAlias(void);'#13#10 + #13#10 +
        '/* external + index */'#13#10 + 'void ExternalIndex(void);'#13#10 + #13#10 + '/* overload */'#13#10 +
        'int OverloadTest(int a);'#13#10 + #13#10 + 'int OverloadTest(int a, int b);'#13#10 + 'double OverloadTest(double a);'#13#10 +
        '/* 字符串默认值包含引号 */'#13#10 + 'char * StringWithQuotes(char * s);'#13#10 + #13#10 +
        '#endif /* ComplexTestUnit_H */'#13#10;

    else source_edit.Text := '';
  end;
end;

procedure Tcode_decl_to_mcp_form.empty_unit_ButtonClick(Sender: TObject);
begin
  case current_language of
    TSourceLanguage.slPascal: source_edit.Text :=
        'unit untitled;' + #13#10 + #13#10 + 'interface' + #13#10 + #13#10 + '// ctrl+v paste decl to here' +
        #13#10 + #13#10 + 'implementation' + #13#10 + #13#10 + 'end.' + #13#10;
    TSourceLanguage.slC: source_edit.Text :=
        '/* untitled.h */' + #13#10 + '#ifndef UNTITLED_H' + #13#10 + '#define UNTITLED_H' + #13#10 + #13#10 +
        '/* ctrl+v paste prototype to here */' + #13#10 + #13#10 + '#endif /* UNTITLED_H */' + #13#10;
    else source_edit.Text := ''
  end;
end;

procedure Tcode_decl_to_mcp_form.Open_unit_readme_Button6Click(Sender: TObject);
var
  ph, fn: U_String;
begin
  ph := umlGetFilePath(ParamStr(0));

  case current_language of
    TSourceLanguage.slPascal: fn := umlCombineFileName(ph, 'pascal_code_mcp_rule.html');
    TSourceLanguage.slC: fn := umlCombineFileName(ph, 'C_code_mcp_rule.html');
    else exit;
  end;

  if umlFileExists(fn) then
    OpenDocument(fn.Text);
end;

procedure Tcode_decl_to_mcp_form.Sel_Lang_ComboBoxChange(Sender: TObject);
begin
  case Sel_Lang_ComboBox.ItemIndex of
    1: //pascal
    begin
      source_edit.Highlighter := FreePascalHighlighter;
      current_language := TSourceLanguage.slPascal;
    end;
    2: //C
    begin
      source_edit.Highlighter := SynCppSyn1;
      current_language := TSourceLanguage.slC;
    end;
    else
    begin
      source_edit.Highlighter := AnyHighlighter;
      current_language := TSourceLanguage.slUnknown;
    end;
  end;
end;

procedure Tcode_decl_to_mcp_form.sel_lang_LabelClick(Sender: TObject);
begin
  Auto_Select_Language;
end;

procedure Tcode_decl_to_mcp_form.source_2_json_nex_ButtonClick(Sender: TObject);
begin
  case current_language of
    TSourceLanguage.slPascal:
    begin
      with tpascal_func_decl_tool.CreateFrom_Pascal_Code(source_edit.Text) do
      begin
        source2json_edit.Text := SaveToJson();
        Free;
      end;
    end;
    TSourceLanguage.slC:
    begin
      with tpascal_func_decl_tool.CreateFrom_C_Code(source_edit.Text) do
      begin
        source2json_edit.Text := SaveToJson();
        Free;
      end;
    end;
    else
    begin
      DoStatus('不支持语言.');
      exit;
    end;
  end;

  MainPageControl.ActivePage := SourceJsonTab;
  DoStatus('源码->json构建.');
end;

procedure Tcode_decl_to_mcp_form.Formater_source_ButtonClick(Sender: TObject);
var
  report: TPascalStringList;
begin
  case current_language of
    TSourceLanguage.slPascal:
    begin
      report := TPascalStringList.Create;
      with tpascal_func_decl_tool.CreateFrom_Pascal_Code(source_edit.Text) do
      begin
        source_edit.Text := decl_to_pascal(report);
        Free;
      end;
    end;
    TSourceLanguage.slC:
    begin
      report := TPascalStringList.Create;
      with tpascal_func_decl_tool.CreateFrom_C_Code(source_edit.Text) do
      begin
        source_edit.Text := decl_to_c(report);
        Free;
      end;
    end;
    else
    begin
      DoStatus('不支持语言.');
      exit;
    end;
  end;

  DoStatus(report.AsText);
  DoStatus('所有代码已重建:只保留顶层函数.');
  DisposeObject(report);
end;

procedure Tcode_decl_to_mcp_form.FormClose(Sender: TObject; var CloseAction: TCloseAction);
begin
  CloseAction := caFree;
end;


procedure Tcode_decl_to_mcp_form.sysTimerTimer(Sender: TObject);
begin
  while LF___.LF_GetStatusCount() > 0 do
    DoStatus(LF___.LF_GetStatusEx());
  Check_Soft_Thread_Synchronize;
  LF___.LF_Sync;
end;

procedure Tcode_decl_to_mcp_form.to_source_ButtonClick(Sender: TObject);
begin
  MainPageControl.ActivePage := SourceTab;
end;

procedure Tcode_decl_to_mcp_form.Backcall_DoStatus(Text_: SystemString; const ID: integer);
begin
  if LogMemo.Lines.Count > 5000 then
    LogMemo.Lines.Clear;
  LogMemo.Lines.Add(UTF8Encode(Text_));
end;

constructor Tcode_decl_to_mcp_form.Create(AOwner: TComponent);
begin
  inherited Create(AOwner);
  current_language := TSourceLanguage.slUnknown;
  AddDoStatusHook(self, Backcall_DoStatus);
end;

destructor Tcode_decl_to_mcp_form.Destroy;
begin
  LF___.LF_Shutdown;
  RemoveDoStatusHook(self);
  inherited Destroy;
end;

procedure Tcode_decl_to_mcp_form.Auto_Select_Language;
begin
  current_language := DetectSourceLanguage(source_edit.Text);
  case current_language of
    slPascal: Sel_Lang_ComboBox.ItemIndex := 1;
    slC: Sel_Lang_ComboBox.ItemIndex := 2;
    else Sel_Lang_ComboBox.ItemIndex := 0;
  end;
  Sel_Lang_ComboBoxChange(Sel_Lang_ComboBox);
end;

end.
