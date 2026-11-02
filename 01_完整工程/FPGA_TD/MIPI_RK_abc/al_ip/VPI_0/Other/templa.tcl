
package require Tcl 8.5
package provide tmpl_parser 0.1

namespace eval ::tmpl_parser {
    namespace export tmpl_parser
}

proc ::tmpl_parser::tmpl_parser {tmpl} {
    set parser { {set _o {}} }
    while {[set i [string first ^> $tmpl]] != -1} {
        set h [expr {$i-1}]
        set j [expr {$i+2}]
        set token [string range $tmpl 0 $h]
        set d [string first <^ $token]
        set c [expr {$d-1}]
        set e [expr {$d+2}]
        set f [expr {$d+3}]

        lappend parser [escaped_parse [string range $token 0 $c]]
        switch [string index $token $e] {
            "=" {
                lappend parser [normal_parse [string range $token $f end]]
            }
            ":" {
                lappend parser [numeric_parse [string range $token $f end]]
            }
            default {
                lappend parser [string range $token $e end]
            }
        }
        set tmpl [string range $tmpl $j end]
    }
    lappend parser [escaped_parse $tmpl]
    lappend parser {join $_o ""}

    return [join $parser "\n"]
}

proc ::tmpl_parser::escaped_parse {str} {
    set str [string map {\" \\\" \{ \\\{ \} \\\} \\ \\\\ \[ \\\[ \] \\\]} $str]
    return "lappend _o \"$str\""
}

proc ::tmpl_parser::normal_parse {str} {
    return "lappend _o $str"
}

proc ::tmpl_parser::numeric_parse {str} {
    return "lappend _o [expr $str]"
}
